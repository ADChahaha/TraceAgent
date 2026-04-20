"""file_extraction_agent 的模型客户端构造层。

实现步骤：

```text
调用方进入 build_extractor_client_from_env(config_path)
  -> 先从 os.environ 读取 BASE_URL、OPENAI_API_KEY、MODEL
  -> 如果缺任何一个，就抛 ExtractorClientConfigError 并指出缺失变量名
  -> 再读取 model_client_config.json，拿到 structured_output.strategy、fallback_order 和 request_options
  -> 校验 strategy 是否是 json_schema / tool_call / auto，校验 fallback_order 只包含支持的方法
  -> 用 env 和 request_options 创建 ChatOpenAI(base_url=..., api_key=..., model=..., ...)
  -> 返回 ExtractorClient，让 broad extraction / resolution 后续按 schema 取结构化 runnable
  -> 调用 ExtractorClient.invoke(...) 时，先把仓库里的 json_schema / tool_call 映射到 LangChain 的 json_schema / function_calling
  -> 如果 strategy=auto，就按 fallback_order 依次尝试；如果前一种不支持，再退到下一种
  -> 成功后把 messages 交给 runnable.invoke(...)，返回 Pydantic 结构化结果；全部失败时抛 ExtractorClientInvocationError
```
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TypeVar

from langchain_openai import ChatOpenAI
from pydantic import BaseModel


SchemaT = TypeVar("SchemaT", bound=BaseModel)
StructuredOutputStrategy = Literal["json_schema", "tool_call", "auto"]
StructuredOutputMethod = Literal["json_schema", "tool_call"]
LangChainStructuredOutputMethod = Literal["json_schema", "function_calling"]

REQUIRED_ENV_VARS = ("BASE_URL", "OPENAI_API_KEY", "MODEL")
SUPPORTED_STRATEGIES = {"json_schema", "tool_call", "auto"}
SUPPORTED_METHODS = {"json_schema", "tool_call"}
DEFAULT_CONFIG_PATH = Path(__file__).with_name("model_client_config.json")
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
    *, config_path: str | Path | None = None
) -> ExtractorClient:
    runtime_config = _load_runtime_config_from_env()
    client_config = _load_client_config(config_path=config_path)
    request_options = dict(client_config["request_options"])
    request_options.setdefault("temperature", 0)

    model = ChatOpenAI(
        base_url=runtime_config["BASE_URL"],
        api_key=runtime_config["OPENAI_API_KEY"],
        model=runtime_config["MODEL"],
        **request_options,
    )
    return ExtractorClient(
        model=model,
        model_name=runtime_config["MODEL"],
        base_url=runtime_config["BASE_URL"],
        structured_output_strategy=client_config["strategy"],
        structured_output_methods=tuple(client_config["methods"]),
    )


def build_model_client_from_env(
    *, config_path: str | Path | None = None
) -> ExtractorClient:
    """兼容旧入口名，避免上层调用点立刻失效。"""

    if config_path is None:
        return build_extractor_client_from_env()
    return build_extractor_client_from_env(config_path=config_path)


def _load_runtime_config_from_env() -> dict[str, str]:
    missing = [name for name in REQUIRED_ENV_VARS if not os.getenv(name)]
    if missing:
        missing_names = ", ".join(missing)
        raise ExtractorClientConfigError(
            f"missing required environment variables: {missing_names}"
        )

    return {name: os.environ[name] for name in REQUIRED_ENV_VARS}


def _load_client_config(
    *, config_path: str | Path | None = None
) -> dict[str, StructuredOutputStrategy | list[StructuredOutputMethod] | dict[str, Any]]:
    raw_config = _read_json_config(config_path=config_path)
    structured_output = raw_config.get("structured_output", {})
    request_options = raw_config.get("request_options", {})

    if not isinstance(structured_output, dict):
        raise ExtractorClientConfigError("structured_output must be an object")
    if not isinstance(request_options, dict):
        raise ExtractorClientConfigError("request_options must be an object")

    strategy = structured_output.get("strategy", "auto")
    if strategy not in SUPPORTED_STRATEGIES:
        supported = ", ".join(sorted(SUPPORTED_STRATEGIES))
        raise ExtractorClientConfigError(
            f"unsupported structured_output.strategy: {strategy}. supported: {supported}"
        )

    raw_fallback_order = structured_output.get(
        "fallback_order", ["json_schema", "tool_call"]
    )
    if not isinstance(raw_fallback_order, list) or not raw_fallback_order:
        raise ExtractorClientConfigError(
            "structured_output.fallback_order must be a non-empty list"
        )

    fallback_order = _validate_method_list(raw_fallback_order)
    methods = (
        fallback_order
        if strategy == "auto"
        else _validate_method_list([strategy], field_name="structured_output.strategy")
    )

    return {
        "strategy": strategy,
        "methods": methods,
        "request_options": request_options,
    }


def _read_json_config(*, config_path: str | Path | None = None) -> dict[str, Any]:
    resolved_path = Path(config_path) if config_path is not None else DEFAULT_CONFIG_PATH
    try:
        return json.loads(resolved_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ExtractorClientConfigError(
            f"model client config not found: {resolved_path}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ExtractorClientConfigError(
            f"invalid model client config json: {resolved_path}"
        ) from exc


def _validate_method_list(
    raw_methods: list[Any], *, field_name: str = "structured_output.fallback_order"
) -> list[StructuredOutputMethod]:
    validated: list[StructuredOutputMethod] = []
    for method in raw_methods:
        if method not in SUPPORTED_METHODS:
            supported = ", ".join(sorted(SUPPORTED_METHODS))
            raise ExtractorClientConfigError(
                f"unsupported {field_name} item: {method}. supported: {supported}"
            )
        validated.append(method)
    return validated
