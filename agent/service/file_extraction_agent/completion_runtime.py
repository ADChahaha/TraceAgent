"""模型/工具输出 → 普通事件队列 → astream 统一输出完成或失败；取消直接关闭。

取消只保存 cancel_requested。producer Task 表达执行结果；跨线程入口安排取消，
流关闭等待 producer 清理，通过取走 on_close 回调保证注册项只移除一次。
"""

from __future__ import annotations

import asyncio
import json
import threading
from contextlib import aclosing
from dataclasses import asdict
from typing import Any, AsyncGenerator, AsyncIterator, Callable

from langchain_core.messages import AIMessage, ToolMessage

from service.file_extraction_agent.core.loop import run_qa_stream
from service.file_extraction_agent.core.contracts import (
    MessageStarted, MessageDelta, ModelRetry, ModelFailed, QaModel,
)
from service.file_extraction_agent.core.messages import _message_stop_signal, _terminal_stop_signals
from service.file_extraction_agent.schemas import DocumentQaMessage, RunOptions

_DONE = object()


async def stream_completion_events(
    *, workspace: dict[str, Any], messages: list[DocumentQaMessage],
    qa_model: QaModel | None = None,
    run_options: RunOptions | None = None, should_stop=None,
) -> AsyncIterator[dict[str, Any]]:
    """仅包装 Agent 普通事件；最终模型失败抛异常，取消向内层传播。"""
    yield {"type": "source_indexed", "tool": "source_index", "result": {"ok": True}}
    async with aclosing(run_qa_stream(
        workspace=workspace, messages=messages, qa_model=qa_model,
        run_options=run_options, should_stop=should_stop,
    )) as outputs:
        async for output in outputs:
            if isinstance(output, MessageStarted):
                yield {"type": "model_message.started", "message_id": output.message_id}
            elif isinstance(output, MessageDelta):
                yield {"type": "model_message.delta", "message_id": output.message_id, "delta": output.delta}
            elif isinstance(output, ModelRetry):
                yield {"type": "model_request.retrying", **asdict(output)}
            elif isinstance(output, ModelFailed):
                raise RuntimeError(output.error)
            elif isinstance(output, AIMessage):
                yield _model_message_event(output)
                for call in output.tool_calls:
                    yield {"type": "tool_started", "tool": call["name"], "args": call["args"], "tool_call_id": call["id"]}
            elif isinstance(output, ToolMessage):
                yield _tool_message_event(output)
            else:
                raise TypeError(f"unexpected agent output: {type(output).__name__}")


def _model_message_event(message: AIMessage) -> dict[str, Any]:
    """提取可见文本、工具调用和终止信号，不携带隐藏推理。"""
    stop_signal = _message_stop_signal(message)
    event = {
        "type": "model_message.done",
        "message_id": message.id or "",
        "content": _message_content_text(message.content),
        "tool_call_count": len(message.tool_calls),
        "tool_calls": [{"id": call["id"], "name": call["name"], "args": call["args"]} for call in message.tool_calls],
        "is_final": not message.tool_calls and stop_signal in _terminal_stop_signals(),
    }
    if stop_signal:
        event["stop_signal"] = stop_signal
    return event


def _tool_message_event(message: ToolMessage) -> dict[str, Any]:
    result = message.artifact
    if result is None:
        try:
            result = json.loads(message.content)
        except (TypeError, json.JSONDecodeError):
            result = message.content
    failed = message.status == "error" or isinstance(result, dict) and result.get("ok") is False
    return {"type": "tool_failed" if failed else "tool_completed", "tool": message.name,
            "args": message.additional_kwargs["tool_args"], "tool_call_id": message.tool_call_id, "result": result}


def _message_content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
            continue
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text" and isinstance(item.get("text"), str):
            parts.append(item["text"])
    return "".join(parts)


class CompletionRuntime:
    """单消费者流：启动 producer → FIFO 普通事件 → 唯一终态出口 → 清理注册项。"""

    def __init__(self, workspace: dict[str, Any], qa_model: QaModel,
                 messages: list[DocumentQaMessage], run_options: RunOptions | None = None,
                 on_close: Callable[[], None] | None = None) -> None:
        self.workspace = workspace
        self.messages = messages
        self.run_options = run_options
        self.model = qa_model
        self.cancel_requested = False
        self._lock = threading.Lock()
        self._producer: asyncio.Task | None = None
        self._queue: asyncio.Queue = asyncio.Queue()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._on_close = on_close
        self._events: AsyncGenerator[dict[str, Any], None] | None = None

    def astream(self) -> AsyncGenerator[dict[str, Any], None]:
        with self._lock:
            if self._events is not None:
                raise RuntimeError("completion stream can only be consumed once")
            self._events = self._stream()
            return self._events

    async def _stream(self) -> AsyncGenerator[dict[str, Any], None]:
        with self._lock:
            if not self.cancel_requested:
                self._loop = asyncio.get_running_loop()
                self._producer = asyncio.create_task(self._produce(), name="qa-completion")
                # Task 在进入函数体前被取消，也必须唤醒队列消费者。
                self._producer.add_done_callback(lambda _: self._queue.put_nowait(_DONE))
        try:
            if self.cancel_requested:
                return
            seq = 1
            yield {"type": "completion.created", "status": "in_progress", "seq": seq}
            while not self.cancel_requested:
                event = await self._queue.get()
                if self.cancel_requested:
                    return
                if event is _DONE:
                    if self._producer.cancelled():
                        return
                    error = self._producer.exception()
                    # 移除注册项后再交付终态，取消入口不会把已完成轮次重新标记。
                    self._notify_closed()
                    if self.cancel_requested:
                        return
                    seq += 1
                    if error is None:
                        yield {"type": "completion.completed", "status": "completed", "seq": seq}
                    else:
                        yield {"type": "completion.failed", "status": "failed", "error_message": str(error), "seq": seq}
                    return
                seq += 1
                yield {**event, "seq": seq}
        finally:
            with self._lock:
                self._loop = None
            self._cancel_producer()
            if self._producer is not None:
                await asyncio.gather(self._producer, return_exceptions=True)
            self._notify_closed()

    stream = astream

    async def _produce(self) -> None:
        async with aclosing(stream_completion_events(
            workspace=self.workspace, messages=self.messages,
            run_options=self.run_options, qa_model=self.model,
            should_stop=lambda: self.cancel_requested,
        )) as events:
            async for event in events:
                with self._lock:
                    if self.cancel_requested:
                        return
                    self._queue.put_nowait(event)

    def terminate(self) -> None:
        """同步取消入口；跨线程只调度取消，不直接操作异步 Task。"""
        with self._lock:
            if self.cancel_requested:
                return
            self.cancel_requested = True
            if self._loop is not None:
                self._loop.call_soon_threadsafe(self._cancel_producer)

    def _cancel_producer(self) -> None:
        task = self._producer
        if task is not None and not task.done() and not task.cancelling():
            task.cancel()

    def _notify_closed(self) -> None:
        with self._lock:
            callback, self._on_close = self._on_close, None
        if callback is not None:
            callback()

    def close(self) -> None:
        """关闭初始化后尚未迭代的运行时；已启动流由其 finally 等待清理。"""
        self.terminate()
        if self._producer is None:
            self._notify_closed()

    async def aclose(self) -> None:
        """调用方停止消费后统一关闭：取消执行 → 关闭事件流 → 等待其 finally 清理。"""
        self.close()
        if self._events is not None:
            await self._events.aclose()


__all__ = ["CompletionRuntime", "stream_completion_events"]
