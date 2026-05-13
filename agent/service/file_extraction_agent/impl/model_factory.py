"""Build the LangChain chat model for the resolution stage."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from service.file_extraction_agent.schemas import ModelConfig


def build_resolution_model(config: ModelConfig | dict | None) -> Any:
    normalized = normalize_model_config(config)
    return build_chat_model(normalized, normalized.resolution_model_name)


def normalize_model_config(config: ModelConfig | dict | None) -> ModelConfig:
    if config is None:
        return _model_config_from_env()
    if isinstance(config, ModelConfig):
        return config
    return ModelConfig(**config)


def build_chat_model(config: ModelConfig, model_name: str) -> Any:
    if config.provider != "openai":
        raise ValueError(f"unsupported provider: {config.provider}")
    if not model_name:
        raise ValueError("model_name is required")

    kwargs: dict[str, Any] = {
        "model": model_name,
        "temperature": config.temperature,
        "max_retries": config.max_retries,
    }
    if config.request_timeout is not None:
        kwargs["request_timeout"] = config.request_timeout
    if config.base_url:
        kwargs["base_url"] = config.base_url
    if config.api_key:
        kwargs["api_key"] = config.api_key
    if config.top_p is not None:
        kwargs["top_p"] = config.top_p
    if config.reasoning_effort:
        kwargs["reasoning_effort"] = config.reasoning_effort
    extra_body: dict[str, Any] = {}
    if config.top_k is not None:
        extra_body["top_k"] = config.top_k
    if _should_enable_deepseek_thinking(config, model_name):
        extra_body["thinking"] = {"type": "enabled"}
    elif _should_disable_deepseek_thinking(config, model_name):
        extra_body["thinking"] = {"type": "disabled"}
    if extra_body:
        kwargs["extra_body"] = extra_body

    model_cls = (
        DeepSeekReasoningChatOpenAI
        if _should_enable_deepseek_thinking(config, model_name)
        else ChatOpenAI
    )
    return model_cls(**kwargs)


class DeepSeekReasoningChatOpenAI(ChatOpenAI):
    """ChatOpenAI variant that round-trips DeepSeek thinking content for tools."""

    def _create_chat_result(
        self,
        response: dict | Any,
        generation_info: dict | None = None,
    ):
        result = super()._create_chat_result(response, generation_info)
        response_dict = response if isinstance(response, dict) else response.model_dump()
        choices = response_dict.get("choices") or []
        for generation, choice in zip(result.generations, choices, strict=False):
            message = choice.get("message") or {}
            reasoning_content = message.get("reasoning_content")
            if reasoning_content and isinstance(generation.message, AIMessage):
                generation.message.additional_kwargs["reasoning_content"] = reasoning_content
        return result

    def _get_request_payload(
        self,
        input_: Any,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        messages = self._convert_input(input_).to_messages()
        for payload_message, source_message in zip(
            payload.get("messages", []),
            messages,
            strict=False,
        ):
            if isinstance(source_message, AIMessage):
                reasoning_content = source_message.additional_kwargs.get("reasoning_content")
                if reasoning_content:
                    payload_message["reasoning_content"] = reasoning_content
        return payload


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
        resolution_model_name=values.get("RESOLUTION_MODEL") or model,
        temperature=_float_env(values.get("TEMPERATURE"), 0.0),
        top_p=_optional_float_env(values.get("TOP_P")),
        top_k=_optional_int_env(values.get("TOP_K")),
        reasoning_effort=values.get("REASONING_EFFORT") or None,
        max_retries=_int_env(values.get("MODEL_MAX_RETRIES"), 6),
        request_timeout=_optional_float_env(values.get("MODEL_REQUEST_TIMEOUT")),
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


def _should_disable_deepseek_thinking(config: ModelConfig, model_name: str) -> bool:
    base_url = (config.base_url or "").lower()
    model = (model_name or "").lower()
    return "api.deepseek.com" in base_url or "deepseek" in model


def _should_enable_deepseek_thinking(config: ModelConfig, model_name: str) -> bool:
    return bool(config.reasoning_effort) and _should_disable_deepseek_thinking(config, model_name)


__all__ = ["build_resolution_model", "normalize_model_config", "build_chat_model"]
