"""单轮问答：执行模型/工具循环 → 包装事件 → 队列提交 → 事件输出与取消收尾。

CompletionRuntime 独立持有输入、模型、生产协程、锁与事件队列。工具结果逐项发布，取消立即中断生产协程及未完成工具，
终态只提交一次；本模块不维护运行时注册表，也不导入 CompletionManager。
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading
from dataclasses import asdict, is_dataclass
from contextlib import aclosing
from typing import Any, AsyncIterator, Callable, Iterable

from langchain_core.messages import AIMessage, ToolMessage

from service.file_extraction_agent.core.loop import run_qa_stream
from service.file_extraction_agent.core.contracts import (
    MessageStarted, MessageDelta, ModelRetry, ModelFailed, QaModel,
)
from service.file_extraction_agent.core.messages import _message_stop_signal, _terminal_stop_signals
from service.file_extraction_agent.schemas import DocumentQaMessage, ResourceRefs, RunOptions


_QUEUE_CANCEL = object()
_QUEUE_DONE = object()


async def stream_completion_events(
    *, resource_path: ResourceRefs, messages: list[DocumentQaMessage],
    qa_model: QaModel | None = None,
    run_options: RunOptions | None = None, should_stop=None,
) -> AsyncIterator[dict[str, Any]]:
    """路径与消息 → loop 模型/单项工具输出 → 业务事件；管理 ID 不进入 graph。"""
    stopped = lambda: should_stop is not None and should_stop()
    yield {"type": "completion.created", "status": "in_progress"}
    yield {"type": "source_indexed", "tool": "source_index", "result": {"ok": True}}
    outputs = run_qa_stream(
        resource_path=resource_path, messages=messages, qa_model=qa_model,
        run_options=run_options, should_stop=should_stop,
    )
    try:
        async for output in outputs:
            if isinstance(output, MessageStarted):
                yield {"type": "model_message.started", "message_id": output.message_id}
            elif isinstance(output, MessageDelta):
                yield {"type": "model_message.delta", "message_id": output.message_id, "delta": output.delta}
            elif isinstance(output, ModelRetry):
                yield {"type": "model_request.retrying", **asdict(output)}
            elif isinstance(output, ModelFailed):
                yield _completion_event("failed", **asdict(output))
                return
            elif isinstance(output, AIMessage):
                yield _model_message_event(output)
                for call in output.tool_calls:
                    yield {"type": "tool_started", "tool": call["name"], "args": call["args"], "tool_call_id": call["id"]}
            elif isinstance(output, ToolMessage):
                yield _tool_message_event(output, {
                    "name": output.name, "args": output.additional_kwargs["tool_args"],
                })
            elif isinstance(output, list):
                for message in output:
                    if not isinstance(message, ToolMessage):
                        raise TypeError("tool batch requires ToolMessage results")
                    yield _tool_message_event(message, {
                        "name": message.name, "args": message.additional_kwargs["tool_args"],
                    })
            else:
                raise TypeError(f"unexpected graph output: {type(output).__name__}")
    except Exception as exc:
        yield {"type": "tool_failed", "tool": "qa", "result": {"ok": False, "errors": [{"message": str(exc)}]}}
        yield _completion_event("cancelled" if stopped() else "failed", error=str(exc))
        return
    finally:
        close = getattr(outputs, "aclose", None)
        if close is not None:
            await close()
    yield _completion_event("cancelled" if stopped() else "completed")


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


def _tool_message_event(message: ToolMessage, call: dict[str, Any]) -> dict[str, Any]:
    result = message.artifact
    if result is None:
        try:
            result = json.loads(message.content)
        except (TypeError, json.JSONDecodeError):
            result = message.content
    failed = message.status == "error" or isinstance(result, dict) and result.get("ok") is False
    return {"type": "tool_failed" if failed else "tool_completed", "tool": call["name"],
            "args": call["args"], "tool_call_id": message.tool_call_id, "result": result}


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


def _plain(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value



class CompletionRuntime:
    """单个 document-QA chat completion 的运行时。

    持有该 completion 专属的 resource_path、messages、qa_model、事件通道 queue 与同步锁。
    它自己完成生产、消费与收尾：

    stream() / astream()（消费入口）
      -> 绑定当前事件循环的 Event，再通过 create_task 启动 producer
      -> 提交队列后通知消费者，按 FIFO 分配 seq 并 yield 字典
      -> finally 断连、取消并等待 producer 清理，解除事件循环绑定，通知 manager 收尾

    _produce()
      -> async for 消费 stream_completion_events(resource_path=..., qa_model=...) 的事件字典
      -> 用 commit_* / commit_terminal_event 投进 queue；异常投 completion.failed；
         兜底 commit_done

    terminate() / get_status() / close()：取消 / 查询状态 / 同步关闭未开始的流。

    on_close 由 manager 注入（remove 闭包），runtime 不接收或保存 completion_id，也不
    导入 manager。stream() 生成器结束或 close() 时通过 _notify_closed 恰好通知一次。

    事件通道 + 终态裁定由 _lock 线性化：cancel 前已提交的事件按 FIFO 先发，cancel
    之后的新事件被拒收；terminal 只提交一次；close_once 保证终态唯一。
    """

    def __init__(self, resource_path: ResourceRefs, qa_model: QaModel,
                 messages: list[DocumentQaMessage], run_options: RunOptions | None = None,
                 on_close: Callable[[], None] | None = None) -> None:
        self.resource_path = resource_path
        self.messages = messages
        self.run_options = run_options
        self.model = qa_model
        self.status: str = "in_progress"
        self.cancel_requested = False
        self.closed = False
        self.terminal_committed = False
        self._lock = threading.Lock()
        self._producer: asyncio.Task | None = None
        self.queue: queue.Queue[dict[str, Any] | object] = queue.Queue()
        self._async_loop: asyncio.AbstractEventLoop | None = None
        self._async_ready: asyncio.Event | None = None
        self._on_close: Callable[[], None] | None = on_close
        self._closed_notified = False

    def _enqueue(self, event: dict[str, Any] | object) -> None:
        """持锁提交 FIFO 事件，再通过事件循环唤醒异步消费者。"""
        self.queue.put(event)
        if self._async_loop is not None:
            self._async_loop.call_soon_threadsafe(self._async_ready.set)

    def _notify_closed(self) -> None:
        """幂等通知 manager 移除注册项；不持锁调用回调。"""
        with self._lock:
            if self._closed_notified:
                return
            self._closed_notified = True
            callback = self._on_close
        if callback is not None:
            callback()

    async def astream(self) -> AsyncIterator[dict[str, Any]]:
        """生产协程提交事件 → Event 唤醒消费者 → FIFO 编号输出；等待不占工作线程。"""
        producer = None
        ready = asyncio.Event()
        with self._lock:
            if self.closed:
                closed = True
            else:
                closed = False
                self._async_loop = asyncio.get_running_loop()
                self._async_ready = ready
                if not self.cancel_requested:
                    producer = asyncio.create_task(self._produce(), name="qa-completion")
                    self._producer = producer
        if closed:
            self._notify_closed()
            return
        next_seq = 1
        try:
            while True:
                ready.clear()
                try:
                    event = self.queue.get_nowait()
                except queue.Empty:
                    await ready.wait()
                    continue
                if event is _QUEUE_CANCEL:
                    if producer is not None:
                        self._cancel_producer()
                        await asyncio.gather(producer, return_exceptions=True)
                    event = _completion_event("cancelled")
                elif event is _QUEUE_DONE:
                    event = _completion_event("completed")
                if not isinstance(event, dict):
                    continue
                status = _terminal_status(event)
                if status is not None and not self.close_once(status):
                    return
                yield _plain({**event, "seq": next_seq})
                next_seq += 1
                if status is not None:
                    return
        finally:
            self.disconnect()
            with self._lock:
                self._async_loop = None
                self._async_ready = None
            if producer is not None:
                if not producer.done() and not producer.cancelling():
                    producer.cancel()
                await asyncio.gather(producer, return_exceptions=True)
            self._producer = None
            self._notify_closed()

    def _cancel_producer(self) -> None:
        task = self._producer
        if task is not None and not task.done() and not task.cancelling():
            task.cancel()

    def stream(self) -> AsyncIterator[dict[str, Any]]:
        return self.astream()

    def close(self) -> None:
        """同步关闭尚未开始迭代的流：断开并通知 manager 移除注册项。"""
        self.disconnect()
        self._notify_closed()

    async def _produce(self) -> None:
        terminal_committed = False
        try:
            async with aclosing(stream_completion_events(
                resource_path=self.resource_path,
                messages=self.messages, run_options=self.run_options, qa_model=self.model,
                should_stop=lambda: self.cancel_requested,
            )) as events:
                async for event in events:
                    if _terminal_status(event) is not None:
                        terminal_committed = self.commit_terminal_event(event)
                        return
                    if not self.commit_event(event):
                        return
        except Exception as exc:
            terminal_committed = self.commit_terminal_event(
                _completion_event("failed", error_message=str(exc)),
            )
        finally:
            if not terminal_committed:
                self.commit_done()

    def disconnect(self) -> None:
        """连接已断：停止后续生产并唤醒 consumer；不等待工具批次补齐。"""
        with self._lock:
            if self.closed:
                return
            self.cancel_requested = True
            self.closed = True
            self.status = "cancelled"
            self._enqueue(_QUEUE_CANCEL)
            if self._async_loop is not None:
                self._async_loop.call_soon_threadsafe(self._cancel_producer)

    def terminate(self) -> str:
        with self._lock:
            if self.closed or self.terminal_committed:
                return self.status
            if self.cancel_requested:
                return self.status
            self.cancel_requested = True
            self.status = "cancelling"
            self._enqueue(_QUEUE_CANCEL)
            if self._async_loop is not None:
                self._async_loop.call_soon_threadsafe(self._cancel_producer)
            return self.status

    def get_status(self) -> str:
        return self.status

    def commit_events(self, events: Iterable[dict[str, Any]]) -> bool:
        with self._lock:
            if self.closed or self.terminal_committed:
                return False
            if self.cancel_requested:
                return False
            active_events = list(events)
            for event in active_events:
                if _terminal_status(event) is not None:
                    continue
                self._enqueue(event)
            return True

    def commit_event(self, event: dict[str, Any]) -> bool:
        return self.commit_events([event])

    def commit_terminal_event(self, event: dict[str, Any]) -> bool:
        status = _terminal_status(event)
        if status is None:
            raise ValueError("expected a completion terminal event")
        with self._lock:
            if self.closed or self.terminal_committed:
                return False
            if self.cancel_requested:
                return False
            self.terminal_committed = True
            self.status = status
            self._enqueue(event)
            return True

    def commit_done(self) -> bool:
        with self._lock:
            if self.cancel_requested or self.closed or self.terminal_committed:
                return False
            self.terminal_committed = True
            self.status = "completed"
            self._enqueue(_QUEUE_DONE)
            return True

    def should_cancel(self) -> bool:
        with self._lock:
            return self.cancel_requested and not self.closed

    def is_closed(self) -> bool:
        with self._lock:
            return self.closed

    def close_once(self, status: str) -> bool:
        with self._lock:
            if self.closed:
                return False
            self.closed = True
            self.status = status
            return True


def _completion_event(status: str, **fields: Any) -> dict[str, Any]:
    return {"type": f"completion.{status}", "status": status, **fields}


def _terminal_status(event: dict[str, Any]) -> str | None:
    """仅由内部事件的 type 决定终态，不解析 SSE 或正文。"""
    return {
        "completion.completed": "completed",
        "completion.cancelled": "cancelled",
        "completion.failed": "failed",
    }.get(event.get("type"))


__all__ = ["CompletionRuntime", "stream_completion_events"]
