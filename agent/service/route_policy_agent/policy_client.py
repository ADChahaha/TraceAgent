"""route policy agent 的小 LLM 结构化调用层。"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any, Literal, TypeVar

from langchain_openai import ChatOpenAI
from pydantic import BaseModel


SchemaT = TypeVar("SchemaT", bound=BaseModel)
StructuredOutputStrategy = Literal["json_schema", "tool_call", "auto"]
StructuredOutputMethod = Literal["json_schema", "tool_call"]
LangChainStructuredOutputMethod = Literal["json_schema", "function_calling"]

SUPPORTED_STRATEGIES = {"json_schema", "tool_call", "auto"}
DEFAULT_AUTO_METHODS: tuple[StructuredOutputMethod, ...] = ("json_schema", "tool_call")
DEFAULT_MODEL = "gpt-5.4-mini"
LANGCHAIN_METHOD_MAP: dict[StructuredOutputMethod, LangChainStructuredOutputMethod] = {
    "json_schema": "json_schema",
    "tool_call": "function_calling",
}


class RoutePolicyClientConfigError(RuntimeError):
    """运行时环境缺少必要模型配置或配置非法时抛出。"""


class RoutePolicyClientInvocationError(RuntimeError):
    """route policy 结构化输出调用失败时抛出。"""


@dataclass(frozen=True)
class RoutePolicyClient:
    """包装底层 ChatOpenAI，统一执行 route policy 结构化输出。"""

    model: ChatOpenAI
    model_name: str
    base_url: str
    structured_output_strategy: StructuredOutputStrategy
    structured_output_methods: tuple[StructuredOutputMethod, ...]

    def invoke(self, *, output_schema: type[SchemaT], messages: Any) -> SchemaT:
        last_error: Exception | None = None
        for method in self.structured_output_methods:
            try:
                runnable = self.model.with_structured_output(
                    output_schema,
                    method=LANGCHAIN_METHOD_MAP[method],
                    strict=True,
                )
                return _coerce_output(output_schema, runnable.invoke(messages))
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                try:
                    raw_message = self.model.invoke(messages)
                except Exception:  # noqa: BLE001
                    continue
                try:
                    return _coerce_output(
                        output_schema,
                        _extract_payload_from_raw_message(raw_message),
                    )
                except Exception:  # noqa: BLE001
                    continue

        attempted = ", ".join(self.structured_output_methods)
        raise RoutePolicyClientInvocationError(
            f"failed to invoke route policy structured output with methods: {attempted}"
        ) from last_error


def build_policy_client(
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    structured_output_strategy: StructuredOutputStrategy = "auto",
) -> RoutePolicyClient:
    methods = _resolve_structured_output_methods(structured_output_strategy)
    runtime_config = _validate_runtime_config(
        base_url=base_url,
        api_key=api_key,
        model=model,
    )

    chat_model = ChatOpenAI(
        base_url=runtime_config["BASE_URL"],
        api_key=runtime_config["OPENAI_API_KEY"],
        model=runtime_config["MODEL"],
        temperature=0,
    )
    return RoutePolicyClient(
        model=chat_model,
        model_name=runtime_config["MODEL"],
        base_url=runtime_config["BASE_URL"],
        structured_output_strategy=structured_output_strategy,
        structured_output_methods=methods,
    )


def _validate_runtime_config(
    *,
    base_url: str | None,
    api_key: str | None,
    model: str | None,
) -> dict[str, str]:
    resolved_base_url = base_url or os.getenv("BASE_URL")
    resolved_api_key = api_key or os.getenv("OPENAI_API_KEY")
    resolved_model = model or os.getenv("MODEL") or DEFAULT_MODEL
    values = {
        "base_url": resolved_base_url,
        "api_key": resolved_api_key,
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        missing_names = ", ".join(missing)
        raise RoutePolicyClientConfigError(
            f"missing required connection parameters: {missing_names}"
        )
    return {
        "BASE_URL": str(resolved_base_url),
        "OPENAI_API_KEY": str(resolved_api_key),
        "MODEL": str(resolved_model),
    }


def _resolve_structured_output_methods(
    structured_output_strategy: StructuredOutputStrategy | str,
) -> tuple[StructuredOutputMethod, ...]:
    if structured_output_strategy not in SUPPORTED_STRATEGIES:
        supported = ", ".join(sorted(SUPPORTED_STRATEGIES))
        raise RoutePolicyClientConfigError(
            "unsupported structured_output_strategy: "
            f"{structured_output_strategy}. supported: {supported}"
        )

    if structured_output_strategy == "auto":
        return DEFAULT_AUTO_METHODS
    return (structured_output_strategy,)


def _coerce_output(output_schema: type[SchemaT], payload: Any) -> SchemaT:
    if isinstance(payload, output_schema):
        return payload
    if isinstance(payload, str):
        return output_schema.model_validate_json(payload)
    if isinstance(payload, dict):
        return output_schema.model_validate(payload)
    if isinstance(payload, BaseModel):
        return output_schema.model_validate(payload.model_dump())
    raise RoutePolicyClientInvocationError(
        f"unsupported route policy payload type: {type(payload)!r}"
    )


def _extract_payload_from_raw_message(raw_message: Any) -> Any:
    additional_kwargs = getattr(raw_message, "additional_kwargs", {}) or {}
    parsed = additional_kwargs.get("parsed")
    if parsed is not None:
        return parsed

    tool_calls = additional_kwargs.get("tool_calls") or []
    for tool_call in tool_calls:
        function_payload = tool_call.get("function") if isinstance(tool_call, dict) else None
        if not function_payload:
            continue
        arguments = function_payload.get("arguments")
        if isinstance(arguments, str) and arguments.strip():
            return json.loads(arguments)

    content = getattr(raw_message, "content", None)
    if isinstance(content, str) and content.strip():
        return content

    raise RoutePolicyClientInvocationError(
        "raw model response does not contain parsed payload, tool call arguments, or text content"
    )
