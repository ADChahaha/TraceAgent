"""service.file_extraction_agent 的模型客户端构造层。

实现步骤：

```text
调用方进入 build_extractor_client(base_url, api_key, model, structured_output_strategy)
  -> 先接住显式传入的 base_url、api_key、model
  -> 如果缺任何一个，就抛 ExtractorClientConfigError 并指出缺失参数名
  -> 校验 structured_output_strategy 是否是 json_schema / tool_call / auto
  -> 用显式连接参数和代码内默认请求参数创建 ChatOpenAI(base_url=..., api_key=..., model=..., temperature=0)
  -> 返回 ExtractorClient，让 broad extraction / resolution 后续按 schema 取结构化 runnable
  -> 调用 ExtractorClient.invoke(...) 时，先把 json_schema / tool_call 映射到 LangChain 的 json_schema / function_calling
  -> 如果 structured_output_strategy=auto，就按代码内固定顺序先试 json_schema，再在不支持时退到 tool_call
  -> 成功后把 messages 交给 runnable.invoke(...)，返回 Pydantic 结构化结果；全部失败时抛 ExtractorClientInvocationError
```
"""

from __future__ import annotations

from dataclasses import dataclass
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


class ExtractorClientConfigError(RuntimeError):
    """运行时环境缺少必要模型配置或配置文件非法时抛出。"""


class ExtractorClientInvocationError(RuntimeError):
    """结构化输出方法全部尝试失败时抛出。"""


@dataclass(frozen=True)
class ExtractorClient:
    """包装底层 ChatOpenAI，统一生成严格结构化输出执行器。"""

    model: ChatOpenAI
    model_name: str
    base_url: str
    structured_output_strategy: StructuredOutputStrategy
    structured_output_methods: tuple[StructuredOutputMethod, ...]

    def with_output_schema(self, output_schema: type[SchemaT]) -> Any:
        last_error: Exception | None = None
        for index, method in enumerate(self.structured_output_methods):
            try:
                return self.model.with_structured_output(
                    output_schema,
                    method=LANGCHAIN_METHOD_MAP[method],
                    strict=True,
                )
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if _should_try_next_structured_method(
                    methods=self.structured_output_methods,
                    current_index=index,
                    error=exc,
                ):
                    continue
                raise ExtractorClientInvocationError(
                    "failed to create structured output runnable "
                    f"with method: {method}"
                ) from exc
        raise _build_all_methods_failed_error(last_error, self.structured_output_methods)

    def invoke(self, *, output_schema: type[SchemaT], messages: Any) -> SchemaT:
        last_error: Exception | None = None
        for index, method in enumerate(self.structured_output_methods):
            try:
                runnable = self.model.with_structured_output(
                    output_schema,
                    method=LANGCHAIN_METHOD_MAP[method],
                    strict=True,
                )
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if _should_try_next_structured_method(
                    methods=self.structured_output_methods,
                    current_index=index,
                    error=exc,
                ):
                    continue
                raise ExtractorClientInvocationError(
                    "failed to create structured output runnable "
                    f"with method: {method}"
                ) from exc

            try:
                return _coerce_output(output_schema, runnable.invoke(messages))
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if _should_try_next_structured_method(
                    methods=self.structured_output_methods,
                    current_index=index,
                    error=exc,
                ):
                    continue
                raise ExtractorClientInvocationError(
                    "failed to invoke structured output runnable "
                    f"with method: {method}"
                ) from exc

        raise _build_all_methods_failed_error(last_error, self.structured_output_methods)


def build_extractor_client(
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    structured_output_strategy: StructuredOutputStrategy = "auto",
) -> ExtractorClient:
    methods = _resolve_structured_output_methods(structured_output_strategy)
    runtime_config = _validate_runtime_config(
        base_url=base_url,
        api_key=api_key,
        model=model,
    )

    model = ChatOpenAI(
        base_url=runtime_config["BASE_URL"],
        api_key=runtime_config["OPENAI_API_KEY"],
        model=runtime_config["MODEL"],
        temperature=0,
    )
    return ExtractorClient(
        model=model,
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
        raise ExtractorClientConfigError(
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
        raise ExtractorClientConfigError(
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
    raise ExtractorClientInvocationError(
        f"unsupported structured output payload type: {type(payload)!r}"
    )


def _should_try_next_structured_method(
    *,
    methods: tuple[StructuredOutputMethod, ...],
    current_index: int,
    error: Exception,
) -> bool:
    if current_index >= len(methods) - 1:
        return False
    if methods[current_index] != "json_schema":
        return False
    return _is_unsupported_structured_output_error(error)


def _is_unsupported_structured_output_error(error: Exception) -> bool:
    message = str(error).lower()
    markers = (
        "unsupported",
        "not supported",
        "does not support",
        "response_format",
    )
    return any(marker in message for marker in markers)


def _build_all_methods_failed_error(
    last_error: Exception | None,
    methods: tuple[StructuredOutputMethod, ...],
) -> ExtractorClientInvocationError:
    attempted = ", ".join(methods)
    error = ExtractorClientInvocationError(
        f"failed to invoke structured output runnable with methods: {attempted}"
    )
    if last_error is not None:
        error.__cause__ = last_error
    return error
