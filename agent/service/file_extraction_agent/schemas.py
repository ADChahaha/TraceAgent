"""Public schemas for document QA completions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ResourceRefProtocol(Protocol):
    """资源定位项的结构化协议：type + location（S3 URL）。

    agent_proto 的 ResourceRef 消息与 schemas.ResourceRef 都满足该结构，
    下游用 ResourceRefs 类型即可同时接受两者。
    """

    type: str
    location: str


ResourceRefs = Sequence[ResourceRefProtocol]


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


class DocumentQaMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: MessageRole
    content: str
    tool_calls: list[dict[str, object]] | None = None
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


class ResourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    location: str


class DocumentQaCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    completion_id: str
    resource_path: list[ResourceRef]
    messages: list[DocumentQaMessage]
    stream: bool = True
    run_options: "RunOptions | None" = None

    @model_validator(mode="after")
    def validate_request(self) -> "DocumentQaCompletionRequest":
        if not self.completion_id.strip():
            raise ValueError("completion_id is required")
        if not self.resource_path:
            raise ValueError("resource_path is required")
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
    tool_execution_timeout: float = 60.0


__all__ = [
    "CompletionStatus",
    "MessageRole",
    "DocumentQaMessage",
    "DocumentQaCompletionRequest",
    "ResourceRef",
    "ResourceRefProtocol",
    "ResourceRefs",
    "ModelConfig",
    "ModelApiTransport",
    "RunOptions",
]
