"""Public schemas for document QA completions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


CompletionStatus = Literal[
    "queued",
    "in_progress",
    "cancelling",
    "cancelled",
    "completed",
    "failed",
]
MessageRole = Literal["system", "user", "assistant", "tool"]
ModelApiTransport = Literal["responses", "chat_completions"]


class InputDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str
    html: str


class DocumentQaMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: MessageRole
    content: str
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    name: str | None = None

    @model_validator(mode="after")
    def validate_content(self) -> "DocumentQaMessage":
        if self.role == "assistant" and self.tool_calls:
            return self
        if not self.content.strip():
            raise ValueError("message content must be non-empty")
        if self.role == "tool" and not (self.tool_call_id or "").strip():
            raise ValueError("tool message requires tool_call_id")
        return self


class DocumentQaCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    completion_id: str
    documents: list[InputDocument]
    messages: list[DocumentQaMessage]
    stream: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
    run_options: "RunOptions | None" = None

    @model_validator(mode="after")
    def validate_request(self) -> "DocumentQaCompletionRequest":
        if not self.completion_id.strip():
            raise ValueError("completion_id is required")
        if not self.documents:
            raise ValueError("documents must be a non-empty list")
        if not self.messages:
            raise ValueError("messages must be a non-empty list")
        return self


@dataclass
class ModelConfig:
    provider: str = "openai"
    base_url: str | None = None
    api_key: str | None = None
    model_name: str = ""
    api_transport: ModelApiTransport | str = "responses"
    temperature: float = 0.0
    top_p: float | None = None
    top_k: int | None = None
    reasoning_effort: str | None = None
    max_retries: int = 0
    request_timeout: float | None = None


@dataclass
class RunOptions:
    max_tool_calls: int = 200
    workspace_root: str | None = None


__all__ = [
    "CompletionStatus",
    "MessageRole",
    "InputDocument",
    "DocumentQaMessage",
    "DocumentQaCompletionRequest",
    "ModelConfig",
    "ModelApiTransport",
    "RunOptions",
]
