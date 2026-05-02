"""HTTP route for the HTML file extraction agent."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from importlib import import_module
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from service.file_extraction_agent.schemas import (
    ExtractionResult,
    ModelConfig,
    RunOptions,
    TaskSpec,
)


router = APIRouter(tags=["file-extraction-agent"])


class ExtractRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    html: str
    task_spec: TaskSpec | dict[str, Any]
    run_options: RunOptions | dict[str, Any] | None = None
    model_config_override: ModelConfig | dict[str, Any] | None = Field(
        default=None,
        alias="model_config",
    )
    base_url: str | None = None
    api_key: str | None = None
    openai_api_key: str | None = None
    broad_model_name: str | None = None
    resolution_model_name: str | None = None
    model: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None


@router.post("/v1/file-extraction-agent/extract")
async def extract_fields(request: ExtractRequest) -> dict[str, Any]:
    try:
        result = await run_in_threadpool(_extract_fields, request)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return _plain(result)


def _extract_fields(request: ExtractRequest) -> ExtractionResult:
    extract = import_module("service.file_extraction_agent.processor").extract
    return extract(
        html=request.html,
        task_spec=request.task_spec,
        run_options=request.run_options,
        model_config=_model_config(request),
    )


def _model_config(request: ExtractRequest) -> ModelConfig | dict[str, Any] | None:
    if request.model_config_override is not None:
        return request.model_config_override

    if not any(
        value is not None
        for value in (
            request.base_url,
            request.api_key,
            request.openai_api_key,
            request.broad_model_name,
            request.resolution_model_name,
            request.model,
            request.temperature,
            request.top_p,
            request.top_k,
        )
    ):
        return None

    default_model = request.model or ""
    return {
        "base_url": request.base_url,
        "api_key": request.api_key or request.openai_api_key,
        "broad_model_name": request.broad_model_name or default_model,
        "resolution_model_name": request.resolution_model_name or default_model,
        "temperature": request.temperature if request.temperature is not None else 0.0,
        "top_p": request.top_p,
        "top_k": request.top_k,
    }


def _plain(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value

