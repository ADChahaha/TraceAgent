"""单轮问答：执行模型/工具循环 → 包装事件 → 队列提交 → 事件输出与取消收尾。

CompletionRuntime 独立持有输入、模型、生产协程、锁与事件队列。已发布工具批次先配齐
结果再取消，终态只提交一次；本模块不维护运行时注册表，也不导入 CompletionManager。
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading
from dataclasses import asdict, is_dataclass
from contextlib import aclosing
from typing import Any, AsyncIterator, Iterable

from langchain_core.messages import AIMessage, ToolMessage

from service.file_extraction_agent.core.loop import run_qa_stream
from service.file_extraction_agent.core.messages import _message_stop_signal, _terminal_stop_signals
from service.file_extraction_agent.core.model import ChatModelFallbackChain
from service.file_extraction_agent.schemas import DocumentQaMessage, RunOptions


_QUEUE_CANCEL = object()
_QUEUE_DONE = object()


async def stream_completion_events(
    *, resource_path: str, messages: list[DocumentQaMessage],
    qa_model: ChatModelFallbackChain | None = None,
    run_options: RunOptions | None = None, should_stop=None,
) -> AsyncIterator[dict[str, Any]]:
    """路径与消息 → graph 批次输出 → 业务事件；管理 ID 不进入 graph。"""
    stopped = lambda: should_stop is not None and should_stop()
    yield {"type": "completion.created", "status": "in_progress"}
    yield {"type": "source_indexed", "tool": "source_index", "result": {"ok": True}}
    outputs = run_qa_stream(
        resource_path=resource_path, messages=messages, qa_model=qa_model,
        run_options=run_options, should_stop=should_stop,
    )
    try:
        async for output in outputs:
            if isinstance(output, AIMessage):
                yield _model_message_event(output)
                for call in output.tool_calls:
                    yield {"type": "tool_started", "tool": call["name"], "args": call["args"], "tool_call_id": call["id"]}
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
        "type": "model_message",
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

    astream()（gRPC 消费入口）
      -> 绑定当前事件循环的 Event，再通过 create_task 启动 producer
      -> 提交队列后通知消费者，按 FIFO 分配 seq 并 yield 字典
      -> finally 断连、取消并等待 producer 清理，解除事件循环绑定

    stream() 是 astream() 的别名，两者均返回异步迭代器。

    _produce()
      -> async for 消费 stream_completion_events(resource_path=..., qa_model=...) 的事件字典
      -> 用 commit_* / commit_terminal_event 投进 queue；异常投 completion.failed；
         兜底 commit_done

    terminate() / get_status()：取消 / 查询状态。

    事件通道 + 终态裁定由 _lock 线性化：cancel 前已提交的事件按 FIFO 先发，cancel
    之后的新事件被拒收；terminal 只提交一次；close_once 保证终态唯一。
    """

    def __init__(self, resource_path: str, qa_model: ChatModelFallbackChain,
                 messages: list[DocumentQaMessage], run_options: RunOptions | None = None) -> None:
        self.resource_path = resource_path
        self.messages = messages
        self.run_options = run_options
        self.model = qa_model
        self.status: str = "in_progress"
        self.cancel_requested = False
        self.closed = False
        self.terminal_committed = False
        self._cancel_deferred = False
        self._lock = threading.Lock()
        self._pending_tool_ids: set[str] = set()
        self.queue: queue.Queue[dict[str, Any] | object] = queue.Queue()
        self._async_loop: asyncio.AbstractEventLoop | None = None
        self._async_ready: asyncio.Event | None = None

    def _enqueue(self, event: dict[str, Any] | object) -> None:
        """持锁提交 FIFO 事件，再通过事件循环唤醒异步消费者。"""
        self.queue.put(event)
        if self._async_loop is not None:
            self._async_loop.call_soon_threadsafe(self._async_ready.set)

    async def astream(self) -> AsyncIterator[dict[str, Any]]:
        """生产协程提交事件 → Event 唤醒消费者 → FIFO 编号输出；等待不占工作线程。"""
        producer = None
        ready = asyncio.Event()
        with self._lock:
            if self.closed:
                return
            self._async_loop = asyncio.get_running_loop()
            self._async_ready = ready
            if not self.cancel_requested:
                producer = asyncio.create_task(self._produce(), name="qa-completion")
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
                if not producer.done():
                    producer.cancel()
                await asyncio.gather(producer, return_exceptions=True)

    def stream(self) -> AsyncIterator[dict[str, Any]]:
        return self.astream()

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

    def terminate(self) -> str:
        with self._lock:
            if self.closed or self.terminal_committed:
                return self.status
            if self.cancel_requested:
                return self.status
            self.cancel_requested = True
            self.status = "cancelling"
            if not self._pending_tool_ids:
                self._enqueue(_QUEUE_CANCEL)
            else:
                self._cancel_deferred = True
            return self.status

    def get_status(self) -> str:
        return self.status

    def commit_events(self, events: Iterable[dict[str, Any]]) -> bool:
        with self._lock:
            if self.closed or self.terminal_committed:
                return False
            if self.cancel_requested and not self._cancel_deferred:
                return False
            active_events = list(events)
            for event in active_events:
                if _terminal_status(event) is not None:
                    continue
                if event.get("type") == "model_message":
                    self._pending_tool_ids.update(call["id"] for call in event.get("tool_calls", []))
                elif event.get("type") in {"tool_completed", "tool_failed"}:
                    self._pending_tool_ids.discard(event.get("tool_call_id"))
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
            if self.cancel_requested and not (self._cancel_deferred and status == "cancelled"):
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
