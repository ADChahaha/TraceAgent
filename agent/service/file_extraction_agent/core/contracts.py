"""核心边界类型：消息与工具输入 → 异步模型/工具协议 → 明确的消息和 JSON 输出。

这里只声明调用契约，不装配依赖或执行流程；SDK 动态结果在 messages 中归一化。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Protocol, TypeAlias, runtime_checkable

from langchain_core.messages import AIMessage, BaseMessage, BaseMessageChunk, ToolCall, ToolMessage
from pydantic import JsonValue

JsonObject: TypeAlias = dict[str, JsonValue]
StopCheck: TypeAlias = Callable[[], bool]


@dataclass(frozen=True)
class ModelCallFailure:
    """单次请求失败；不进入消息历史，取消异常不转换为此类型。"""

    error: str
    retry_after_seconds: float | None = None


@dataclass(frozen=True)
class MessageStarted:
    message_id: str


@dataclass(frozen=True)
class MessageDelta:
    message_id: str
    delta: str


@dataclass(frozen=True)
class ModelRetry:
    message_id: str
    attempt: int
    max_attempts: int
    retry_delay_ms: int
    error: str


@dataclass(frozen=True)
class ModelFailed:
    message_id: str
    error: str


AgentOutput: TypeAlias = AIMessage | ToolMessage | MessageStarted | MessageDelta | ModelRetry | ModelFailed


@runtime_checkable
class AsyncTool(Protocol):
    @property
    def name(self) -> str: ...

    def ainvoke(self, input: dict[str, object]) -> Awaitable[object]: ...


class SyncTool(Protocol):
    @property
    def name(self) -> str: ...

    def invoke(self, input: dict[str, object]) -> object: ...


Tool: TypeAlias = AsyncTool | SyncTool


class ChatModel(Protocol):
    def astream(self, input: Sequence[BaseMessage]) -> AsyncIterator[BaseMessageChunk]: ...

    def ainvoke(self, input: Sequence[BaseMessage]) -> Awaitable[BaseMessage]: ...


@dataclass
class ModelCallAttempt:
    name: str
    model: ChatModel
    use_stream: bool


@runtime_checkable
class ModelAttempts(Protocol):
    def model_call_attempts(self) -> list[ModelCallAttempt]: ...


BoundModel: TypeAlias = ChatModel | ModelAttempts


class QaModel(Protocol):
    def bind_tools(self, tools: Sequence[Tool]) -> BoundModel: ...


ModelInvoker: TypeAlias = Callable[[BoundModel, Sequence[BaseMessage]], Awaitable[AIMessage | ModelCallFailure]]


class ToolExecutor(Protocol):
    def __call__(
        self, tool_calls: list[ToolCall], tools: Sequence[Tool], timeout: float = 60.0,
        *, on_result: Callable[[ToolMessage], None] | None = None,
    ) -> Awaitable[list[ToolMessage]]: ...
