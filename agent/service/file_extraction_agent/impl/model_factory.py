"""Build LangChain chat models for broad and resolution stages."""

from __future__ import annotations

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
        return ModelConfig()
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
    }
    if config.base_url:
        kwargs["base_url"] = config.base_url
    if config.api_key:
        kwargs["api_key"] = config.api_key
    if config.top_p is not None:
        kwargs["model_kwargs"] = {"top_p": config.top_p}
    if config.top_k is not None:
        kwargs.setdefault("model_kwargs", {})["top_k"] = config.top_k

    return ChatOpenAI(**kwargs)


__all__ = ["build_stage_models", "normalize_model_config", "build_chat_model"]
