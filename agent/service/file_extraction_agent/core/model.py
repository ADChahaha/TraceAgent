"""环境配置或 ModelConfig → 校验 provider/传输 → 延迟加载 ChatOpenAI → 单一模型。

Responses/Chat Completions 由 use_responses_api 选择，生产调用固定流式、SDK 重试关闭。
无效配置抛 TypeError/ValueError；本模块不再保存候选列表或注入厂商专用参数。
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TypedDict

from pydantic import SecretStr
from traceagent_shared.config import (
    get_float,
    get_int,
    get_optional_float,
    get_optional_int,
    get_optional_str,
    get_str,
    load_config,
)

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


def _model_config_from_env(config_path: str | Path | None = None) -> ModelConfig:
    config = load_config(config_path)
    return ModelConfig(
        provider=get_str(config, "model", "provider", "PROVIDER", "openai"),
        base_url=get_optional_str(config, "model", "base_url", "BASE_URL"),
        api_key=get_optional_str(config, "model", "api_key", "OPENAI_API_KEY"),
        model_name=get_optional_str(config, "model", "model", "MODEL") or "",
        api_transport=_normalize_api_transport(
            get_optional_str(config, "model", "api_transport", "MODEL_API_TRANSPORT")
        ),
        temperature=get_float(config, "model", "temperature", "TEMPERATURE", 0.0),
        top_p=get_optional_float(config, "model", "top_p", "TOP_P"),
        top_k=get_optional_int(config, "model", "top_k", "TOP_K"),
        reasoning_effort=get_optional_str(config, "model", "reasoning_effort", "REASONING_EFFORT"),
        max_retries=get_int(config, "model", "max_retries", "MODEL_MAX_RETRIES", 0),
        request_timeout=get_optional_float(config, "model", "request_timeout", "MODEL_REQUEST_TIMEOUT")
        or DEFAULT_MODEL_REQUEST_TIMEOUT_SECONDS,
    )


def load_title_model_config(config_path: str | Path | None = None) -> ModelConfig:
    """读取 `[title_model]` 配置，任意未配置项自动回退复用 `[model]`。"""
    config = load_config(config_path)
    base = _model_config_from_env(config_path)
    return ModelConfig(
        provider=get_str(config, "title_model", "provider", "TITLE_PROVIDER", base.provider),
        base_url=get_optional_str(config, "title_model", "base_url", "TITLE_BASE_URL", base.base_url),
        api_key=get_optional_str(config, "title_model", "api_key", "TITLE_OPENAI_API_KEY", base.api_key),
        model_name=get_optional_str(config, "title_model", "model", "TITLE_MODEL", base.model_name) or "",
        api_transport=_normalize_api_transport(
            get_optional_str(config, "title_model", "api_transport", "TITLE_MODEL_API_TRANSPORT", base.api_transport)
        ),
        temperature=get_float(config, "title_model", "temperature", "TITLE_TEMPERATURE", base.temperature),
        top_p=get_optional_float(config, "title_model", "top_p", "TITLE_TOP_P", base.top_p),
        top_k=get_optional_int(config, "title_model", "top_k", "TITLE_TOP_K", base.top_k),
        reasoning_effort=get_optional_str(
            config, "title_model", "reasoning_effort", "TITLE_REASONING_EFFORT", base.reasoning_effort
        ),
        max_retries=get_int(config, "title_model", "max_retries", "TITLE_MODEL_MAX_RETRIES", base.max_retries),
        request_timeout=get_optional_float(
            config,
            "title_model",
            "request_timeout",
            "TITLE_MODEL_REQUEST_TIMEOUT",
            base.request_timeout,
        )
        or DEFAULT_MODEL_REQUEST_TIMEOUT_SECONDS,
    )
