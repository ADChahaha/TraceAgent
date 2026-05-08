"""Build LangChain chat models for broad and resolution stages."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from langchain_openai import ChatOpenAI

from service.file_extraction_agent.schemas import ModelConfig


def build_stage_models(config: ModelConfig | dict | None) -> tuple[Any, Any]:
    normalized = normalize_model_config(config)
    broad_model = build_chat_model(normalized, normalized.broad_model_name)
    resolution_model = build_chat_model(normalized, normalized.resolution_model_name)
    return broad_model, resolution_model


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
    if config.top_k is not None:
        kwargs["extra_body"] = {"top_k": config.top_k}

    return ChatOpenAI(**kwargs)


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
        broad_model_name=values.get("BROAD_MODEL") or model,
        resolution_model_name=values.get("RESOLUTION_MODEL") or model,
        temperature=_float_env(values.get("TEMPERATURE"), 0.0),
        top_p=_optional_float_env(values.get("TOP_P")),
        top_k=_optional_int_env(values.get("TOP_K")),
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


__all__ = ["build_stage_models", "normalize_model_config", "build_chat_model"]
