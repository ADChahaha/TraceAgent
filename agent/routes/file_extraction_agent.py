"""HTTP route for the streaming file extraction agent."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from service.file_extraction_agent.schemas import (
    InputDocument,
    ModelConfig,
    RunOptions,
    TaskSpec,
)


router = APIRouter(tags=["file-extraction-agent"])


class ExtractStreamRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    documents: list[InputDocument]
    task_spec: TaskSpec | dict[str, Any]
    run_options: RunOptions | dict[str, Any] | None = None
    model_config_override: ModelConfig | dict[str, Any] | None = Field(
        default=None,
        alias="model_config",
    )
    base_url: str | None = None
    api_key: str | None = None
    openai_api_key: str | None = None
    resolution_model_name: str | None = None
    model: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None


@router.post("/v1/file-extraction-agent/extract/stream")
async def extract_fields_stream(request: ExtractStreamRequest) -> StreamingResponse:
    try:
        stream = _extract_fields_stream(request)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return StreamingResponse(stream, media_type="application/x-ndjson")


def _extract_fields_stream(request: ExtractStreamRequest):
    extract_stream = import_module("service.file_extraction_agent.processor").extract_stream
    return extract_stream(
        documents=request.documents,
        task_spec=request.task_spec,
        run_options=request.run_options,
        model_config=_model_config(request),
    )


def _model_config(request: ExtractStreamRequest) -> ModelConfig | dict[str, Any] | None:
    if request.model_config_override is not None:
        return request.model_config_override

    if not any(
        value is not None
        for value in (
            request.base_url,
            request.api_key,
            request.openai_api_key,
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
        "resolution_model_name": request.resolution_model_name or default_model,
        "temperature": request.temperature if request.temperature is not None else 0.0,
        "top_p": request.top_p,
        "top_k": request.top_k,
    }
