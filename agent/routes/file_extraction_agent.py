"""HTTP routes for document QA chat completions."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from service.file_extraction_agent.schemas import (
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
    stream: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
    run_options: RunOptions | None = None
    model_config_override: ModelConfig | None = Field(
        default=None,
        alias="model_config",
    )
    base_url: str | None = None
    api_key: str | None = None
    openai_api_key: str | None = None
    model: str | None = None
    api_transport: str | None = None
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
    completion_manager = import_module("service.file_extraction_agent.manager").completion_manager
    return completion_manager.terminate(completion_id)


def _create_chat_completion_stream(request: ChatCompletionRequest):
    completion_manager = import_module("service.file_extraction_agent.manager").completion_manager
    return completion_manager.create(
        completion_id=request.completion_id,
        task_id=request.metadata.get("task_id"),
        documents=request.documents,
        messages=request.messages,
        run_options=request.run_options,
        model_config=_model_config(request),
    )


def _model_config(request: ChatCompletionRequest) -> ModelConfig | None:
    if request.model_config_override is not None:
        return request.model_config_override

    if not any(
        value is not None
        for value in (
            request.base_url,
            request.api_key,
            request.openai_api_key,
            request.model,
            request.api_transport,
            request.temperature,
            request.top_p,
            request.top_k,
        )
    ):
        return None

    return ModelConfig(
        base_url=request.base_url,
        api_key=request.api_key or request.openai_api_key,
        model_name=request.model or "",
        api_transport=request.api_transport or "responses",
        temperature=request.temperature if request.temperature is not None else 0.0,
        top_p=request.top_p,
        top_k=request.top_k,
    )
