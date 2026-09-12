"""问答契约：消息与配置输入 → application 执行 → 类型化业务事件。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Protocol, Sequence

from pydantic import BaseModel, ConfigDict, JsonValue, model_validator


class Unset(Enum):
    """区分未提供的动态字段与显式 JSON null。"""

    VALUE = "unset"


@dataclass
class CompletionToolCall:
    id: str
    name: str
    args: JsonValue


@dataclass
class CompletionEvent:
    """业务事件：application 确定语义和序号，传输层只负责字段编码。"""

    type: str
    seq: int = 0
    status: str | None = None
    message_id: str | None = None
    content: str | None = None
    delta: str | None = None
    tool_call_count: int | None = None
    tool_calls: list[CompletionToolCall] = field(default_factory=list)
    is_final: bool | None = None
    stop_signal: str | None = None
    tool: str | None = None
    tool_call_id: str | None = None
    args: JsonValue | Unset = Unset.VALUE
    result: JsonValue | Unset = Unset.VALUE
    attempt: int | None = None
    max_attempts: int | None = None
    retry_delay_ms: int | None = None
    error: str | None = None
    error_message: str | None = None


class ResourceRefProtocol(Protocol):
    """资源定位项的结构化协议：type + location（S3 URL）。

    agent_proto 的 ResourceRef 消息与 schemas.ResourceRef 都满足该结构，
    下游用 ResourceRefs 类型即可同时接受两者。
    """

    type: str
    location: str


ResourceRefs = Sequence[ResourceRefProtocol]


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
    "MessageRole",
    "DocumentQaMessage",
    "ResourceRef",
    "ResourceRefProtocol",
    "ResourceRefs",
    "ModelConfig",
    "ModelApiTransport",
    "RunOptions",
]
