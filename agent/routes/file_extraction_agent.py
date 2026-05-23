"""HTTP routes for document QA chat completions."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from service.file_extraction_agent.schemas import (
    DocumentQaMemory,
    DocumentQaMessage,
    InputDocument,
    ModelConfig,
    RunOptions,
)


router = APIRouter(tags=["document-qa"])


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    completion_id: str
    documents: list[InputDocument]
    messages: list[DocumentQaMessage]
    memory: DocumentQaMemory = Field(default_factory=DocumentQaMemory)
    stream: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
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


@router.post("/v1/document-qa/chat/completions")
async def create_chat_completion(request: ChatCompletionRequest) -> StreamingResponse:
    try:
        stream = _create_chat_completion_stream(request)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return StreamingResponse(stream, media_type="text/event-stream")


@router.get("/v1/document-qa/chat/completions/{completion_id}")
async def get_chat_completion(completion_id: str) -> dict[str, Any]:
    del completion_id
    return {"status": "not_implemented"}


@router.post("/v1/document-qa/chat/completions/{completion_id}/cancel")
async def cancel_chat_completion(completion_id: str) -> dict[str, Any]:
    cancel_completion = import_module("service.file_extraction_agent.processor").cancel_completion
    return cancel_completion(completion_id)


def _create_chat_completion_stream(request: ChatCompletionRequest):
    create_completion_stream = import_module("service.file_extraction_agent.processor").create_completion_stream
    return create_completion_stream(
        completion_id=request.completion_id,
        documents=request.documents,
        messages=request.messages,
        memory=request.memory,
        run_options=request.run_options,
        model_config=_model_config(request),
    )


def _model_config(request: ChatCompletionRequest) -> ModelConfig | dict[str, Any] | None:
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
