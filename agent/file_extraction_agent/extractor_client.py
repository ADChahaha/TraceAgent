"""file_extraction_agent 的模型客户端构造层。

实现步骤：

```text
调用方进入 build_extractor_client_from_env(structured_output_strategy)
  -> 先从 os.environ 读取 BASE_URL、OPENAI_API_KEY、MODEL
  -> 如果缺任何一个，就抛 ExtractorClientConfigError 并指出缺失变量名
  -> 校验 structured_output_strategy 是否是 json_schema / tool_call / auto
  -> 用 env 和代码内默认请求参数创建 ChatOpenAI(base_url=..., api_key=..., model=..., temperature=0)
  -> 返回 ExtractorClient，让 broad extraction / resolution 后续按 schema 取结构化 runnable
  -> 调用 ExtractorClient.invoke(...) 时，先把 json_schema / tool_call 映射到 LangChain 的 json_schema / function_calling
  -> 如果 structured_output_strategy=auto，就按代码内固定顺序先试 json_schema，再在不支持时退到 tool_call
  -> 成功后把 messages 交给 runnable.invoke(...)，返回 Pydantic 结构化结果；全部失败时抛 ExtractorClientInvocationError
```
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal, TypeVar

from langchain_openai import ChatOpenAI
from pydantic import BaseModel


SchemaT = TypeVar("SchemaT", bound=BaseModel)
StructuredOutputStrategy = Literal["json_schema", "tool_call", "auto"]
StructuredOutputMethod = Literal["json_schema", "tool_call"]
LangChainStructuredOutputMethod = Literal["json_schema", "function_calling"]

REQUIRED_ENV_VARS = ("BASE_URL", "OPENAI_API_KEY", "MODEL")
SUPPORTED_STRATEGIES = {"json_schema", "tool_call", "auto"}
DEFAULT_AUTO_METHODS: tuple[StructuredOutputMethod, ...] = ("json_schema", "tool_call")
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
        for method in self.structured_output_methods:
            try:
                return self.model.with_structured_output(
                    output_schema,
                    method=LANGCHAIN_METHOD_MAP[method],
                    strict=True,
                )
            except Exception as exc:  # noqa: BLE001
                last_error = exc
        attempted = ", ".join(self.structured_output_methods)
        raise ExtractorClientInvocationError(
            f"failed to create structured output runnable with methods: {attempted}"
        ) from last_error

    def invoke(self, *, output_schema: type[SchemaT], messages: Any) -> SchemaT:
        runnable = self.with_output_schema(output_schema)
        return runnable.invoke({"messages": messages})


def build_extractor_client_from_env(
    *,
    structured_output_strategy: StructuredOutputStrategy = "auto",
) -> ExtractorClient:
    runtime_config = _load_runtime_config_from_env()
    methods = _resolve_structured_output_methods(structured_output_strategy)

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


def _load_runtime_config_from_env() -> dict[str, str]:
    missing = [name for name in REQUIRED_ENV_VARS if not os.getenv(name)]
    if missing:
        missing_names = ", ".join(missing)
        raise ExtractorClientConfigError(
            f"missing required environment variables: {missing_names}"
        )

    return {name: os.environ[name] for name in REQUIRED_ENV_VARS}


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
