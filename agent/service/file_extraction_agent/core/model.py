"""环境配置或 ModelConfig → 校验 provider/传输 → 延迟加载 ChatOpenAI → 单一模型。

Responses/Chat Completions 由 use_responses_api 选择，生产调用固定流式、SDK 重试关闭。
无效配置抛 TypeError/ValueError；本模块不再保存候选列表或注入厂商专用参数。
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path
from typing import TypedDict

from pydantic import SecretStr

from service.file_extraction_agent.core.contracts import BoundModel, ChatModel, JsonObject, Tool

from service.file_extraction_agent.schemas import ModelConfig

DEFAULT_MODEL_REQUEST_TIMEOUT_SECONDS = 8.0


def _chat_model_class():
    """真正装配模型时才加载 SDK，服务启动和工具 worker 不加载模型重依赖。"""
    from langchain_openai import ChatOpenAI

    return ChatOpenAI


class ChatModelOptions(TypedDict, total=False):
    model: str
    temperature: float
    max_retries: int
    timeout: float
    base_url: str
    api_key: SecretStr
    top_p: float
    reasoning_effort: str
    extra_body: JsonObject


def build_qa_model(config: ModelConfig | None) -> "ConfiguredChatModel":
    normalized = normalize_model_config(config)
    return build_chat_model(normalized, normalized.model_name)


def normalize_model_config(config: ModelConfig | None) -> ModelConfig:
    if config is None:
        return _model_config_from_env()
    if isinstance(config, ModelConfig):
        return config
    raise TypeError(f"unexpected model config type: {type(config).__name__}")


def build_chat_model(config: ModelConfig, model_name: str) -> "ConfiguredChatModel":
    if config.provider != "openai":
        raise ValueError(f"unsupported provider: {config.provider}")
    if not model_name:
        raise ValueError("model_name is required")
    transport = _normalize_api_transport(config.api_transport)

    kwargs: ChatModelOptions = {
        "model": model_name,
        "temperature": config.temperature,
        # 图统一控制五次请求，禁用 SDK 内层重试，避免次数相乘。
        "max_retries": 0,
    }
    kwargs["timeout"] = config.request_timeout or DEFAULT_MODEL_REQUEST_TIMEOUT_SECONDS
    if config.base_url:
        kwargs["base_url"] = config.base_url
    if config.api_key:
        kwargs["api_key"] = SecretStr(config.api_key)
    if config.top_p is not None:
        kwargs["top_p"] = config.top_p
    if config.reasoning_effort:
        kwargs["reasoning_effort"] = config.reasoning_effort
    extra_body: JsonObject = {}
    if config.top_k is not None:
        extra_body["top_k"] = config.top_k
    if extra_body:
        kwargs["extra_body"] = extra_body

    model = _chat_model_class()(
        **kwargs, use_responses_api=transport == "responses", streaming=True,
    )
    return ConfiguredChatModel(model)


class ConfiguredChatModel:
    """单个 provider → 绑定工具 → BoundModel，保留显式流式或非流式调用方式。"""

    def __init__(self, model: ChatModel, *, use_stream: bool = True):
        self.model = model
        self.use_stream = use_stream

    def bind_tools(self, tools: Sequence[Tool]) -> BoundModel:
        bind = getattr(self.model, "bind_tools", None)
        model = bind(tools) if callable(bind) else self.model
        return BoundModel(model, self.use_stream)


def _normalize_api_transport(value: str | None) -> str:
    normalized = (value or "responses").strip().lower()
    if normalized in {"responses", "chat_completions"}:
        return normalized
    raise ValueError("MODEL_API_TRANSPORT must be responses or chat_completions")


def _model_config_from_env() -> ModelConfig:
    values: dict[str, str] = {}
    for path in _candidate_env_paths():
        values.update(_read_env_file(path))
    values.update(os.environ)
    model = values.get("MODEL", "")
    return ModelConfig(
        provider=values.get("PROVIDER", "openai"),
        base_url=values.get("BASE_URL") or None,
        api_key=values.get("OPENAI_API_KEY") or None,
        model_name=model,
        api_transport=_normalize_api_transport(values.get("MODEL_API_TRANSPORT")),
        temperature=_float_env(values.get("TEMPERATURE"), 0.0),
        top_p=_optional_float_env(values.get("TOP_P")),
        top_k=_optional_int_env(values.get("TOP_K")),
        reasoning_effort=values.get("REASONING_EFFORT") or None,
        max_retries=_int_env(values.get("MODEL_MAX_RETRIES"), 0),
        request_timeout=_optional_float_env(values.get("MODEL_REQUEST_TIMEOUT"))
        or DEFAULT_MODEL_REQUEST_TIMEOUT_SECONDS,
    )


def _candidate_env_paths() -> list[Path]:
    package_env = Path(__file__).resolve().parents[3] / ".env"
    cwd_env = Path.cwd() / ".env"
    if cwd_env == package_env:
        return [package_env]
    return [package_env, cwd_env]


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _float_env(value: str | None, default: float) -> float:
    if value in {None, ""}:
        return default
    return float(value)


def _optional_float_env(value: str | None) -> float | None:
    if value in {None, ""}:
        return None
    return float(value)


def _optional_int_env(value: str | None) -> int | None:
    if value in {None, ""}:
        return None
    return int(value)


def _int_env(value: str | None, default: int) -> int:
    if value in {None, ""}:
        return default
    return int(value)
