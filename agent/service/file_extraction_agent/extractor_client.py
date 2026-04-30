"""service.file_extraction_agent 的模型客户端构造层。

实现步骤：

```text
调用方进入 build_extractor_client(base_url, api_key, model, structured_output_strategy)
  -> 先接住显式传入的 base_url、api_key、model
  -> 如果缺任何一个，就抛 ExtractorClientConfigError 并指出缺失参数名
  -> 校验 structured_output_strategy 只能是 tool_call
  -> 用显式连接参数和代码内默认请求参数创建 ChatOpenAI(base_url=..., api_key=..., model=..., temperature=0)
  -> 返回 ExtractorClient，让 broad extraction / resolution 后续按 schema 取结构化 runnable
  -> 调用 ExtractorClient.invoke(...) 时，把 tool_call 映射到 LangChain 的 function_calling
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
StructuredOutputStrategy = Literal["tool_call"]
LangChainStructuredOutputMethod = Literal["function_calling"]

SUPPORTED_STRATEGY = "tool_call"
DEFAULT_MODEL = "gpt-5.4-mini"
LANGCHAIN_METHOD_MAP: dict[StructuredOutputStrategy, LangChainStructuredOutputMethod] = {
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

    def with_output_schema(self, output_schema: type[SchemaT]) -> Any:
        try:
            return self.model.with_structured_output(
                output_schema,
                method=LANGCHAIN_METHOD_MAP[self.structured_output_strategy],
                strict=True,
            )
        except Exception as exc:  # noqa: BLE001
            raise ExtractorClientInvocationError(
                "failed to create structured output runnable with method: tool_call"
            ) from exc

    def invoke(
        self,
        *,
        output_schema: type[SchemaT],
        messages: Any,
        tools: Any | None = None,
    ) -> SchemaT:
        del tools
        try:
            runnable = self.model.with_structured_output(
                output_schema,
                method=LANGCHAIN_METHOD_MAP[self.structured_output_strategy],
                strict=True,
            )
        except Exception as exc:  # noqa: BLE001
            raise ExtractorClientInvocationError(
                "failed to create structured output runnable with method: tool_call"
            ) from exc

        try:
            return _coerce_output(output_schema, runnable.invoke(messages))
        except Exception as exc:  # noqa: BLE001
            raise ExtractorClientInvocationError(
                "failed to invoke structured output runnable with method: tool_call"
            ) from exc


def build_extractor_client(
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    structured_output_strategy: StructuredOutputStrategy | str = "tool_call",
) -> ExtractorClient:
    strategy = _validate_structured_output_strategy(structured_output_strategy)
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
        structured_output_strategy=strategy,
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


def _validate_structured_output_strategy(
    structured_output_strategy: StructuredOutputStrategy | str,
) -> StructuredOutputStrategy:
    if structured_output_strategy != SUPPORTED_STRATEGY:
        raise ExtractorClientConfigError(
            "unsupported structured_output_strategy: "
            f"{structured_output_strategy}. only supported structured_output_strategy: tool_call"
        )
    return "tool_call"


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
