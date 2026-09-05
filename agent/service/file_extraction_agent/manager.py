"""问答生命周期：校验资源路径 → 注册 completion → graph 执行 → SSE 事件 → 释放运行时。

manager 保存管理 ID，graph 只接收路径和执行参数。资源由 document_resources 管理，
本轮结束不删除资源。ActiveCompletion 用队列和锁保证取消、事件顺序及终态唯一。
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
import queue
import re
import threading
from typing import Any, Iterable

from langchain_core.messages import AIMessage, ToolMessage

from service.document_resources import load_resource

from service.file_extraction_agent.core.loop import run_qa_stream, _message_stop_signal, _terminal_stop_signals
from service.file_extraction_agent.core.model import ChatModelFallbackChain, build_qa_model
from service.file_extraction_agent.schemas import DocumentQaMessage, ModelConfig, RunOptions


_QUEUE_CANCEL = object()
_QUEUE_DONE = object()

def stream_completion_events(
    *, completion_id: str, resource_path: str, messages: list[DocumentQaMessage],
    qa_model: ChatModelFallbackChain | None = None,
    run_options: RunOptions | None = None, should_stop=None,
) -> Iterable[dict[str, Any]]:
    """路径与消息 → graph 批次输出 → 业务事件；管理 ID 不进入 graph。"""
    stopped = lambda: should_stop is not None and should_stop()
    document = load_resource(resource_path).document
    yield {"id": completion_id, "type": "completion.created", "status": "in_progress"}
    yield {"type": "source_indexed", "tool": "source_index", "result": {
        "ok": True, "workspace_root": str(document.root), "tree": _file_tree_lines(document),
    }}
    outputs = run_qa_stream(
        resource_path=resource_path, messages=messages, qa_model=qa_model,
        run_options=run_options, should_stop=should_stop,
    )
    try:
        for output in outputs:
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
        yield _completion_event(completion_id, "cancelled" if stopped() else "failed", error=str(exc))
        return
    finally:
        close = getattr(outputs, "close", None)
        if close is not None:
            close()
    yield _completion_event(completion_id, "cancelled" if stopped() else "completed")


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


def _file_tree_lines(document: Any) -> list[str]:
    lines: list[str] = []

    def walk(path: str | None, prefix: str) -> None:
        entries = document.entries(path)
        for index, entry in enumerate(entries):
            current_last = index == len(entries) - 1
            connector = "└── " if current_last else "├── "
            suffix = "/" if entry.kind == "dir" else ""
            lines.append(f"{prefix}{connector}{entry.name}{suffix}")
            if entry.kind == "dir":
                next_prefix = prefix + ("    " if current_last else "│   ")
                walk(entry.path, next_prefix)

    walk(None, "")
    return lines


def _sse(event: dict[str, Any]) -> str:
    event_type = event.get("type", "message")
    data = json.dumps(_plain(event), ensure_ascii=False, separators=(",", ":"))
    return f"event: {event_type}\ndata: {data}\n\n"


def _plain(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value



class ActiveCompletion:
    """单个 document-QA chat completion 的运行时。

    持有该 completion 专属的 resource_path、messages、qa_model、事件通道 queue 与同步锁。
    它自己完成生产、消费与收尾：

    stream()
      -> 首次迭代时启动 producer 线程（target=_produce）
      -> 循环 queue.get() 取事件：普通事件编码为 SSE 后 yield；_QUEUE_CANCEL/_QUEUE_DONE/终态事件
         则 close_once 后收口并结束
      -> finally 确保终态唯一并释放运行时（注册表移除由 CompletionManager 托管）

    _produce()
      -> 后台线程目标，循环 stream_completion_events(resource_path=..., qa_model=...) 产事件字典
      -> 用 commit_* / commit_terminal_event 投进 queue；异常投 completion.failed；
         兜底 commit_done

    terminate() / get_status()：取消 / 查询状态。

    事件通道 + 终态裁定由 _lock 线性化：cancel 前已提交的事件按 FIFO 先发，cancel
    之后的新事件被拒收；terminal 只提交一次；close_once 保证终态唯一。
    """

    def __init__(self, completion_id: str, resource_path: str, qa_model: ChatModelFallbackChain,
                 messages: list[DocumentQaMessage], run_options: RunOptions | None = None) -> None:
        self.completion_id = completion_id
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

    def stream(self) -> Iterable[str]:
        def run() -> Iterable[str]:
            next_seq = 1

            def encode(event: dict[str, Any]) -> str:
                nonlocal next_seq
                frame = _sse({**event, "seq": next_seq})
                next_seq += 1
                return frame

            if not self.should_cancel():
                producer = threading.Thread(
                    target=self._produce,
                    name=f"qa-completion-{self.completion_id}",
                    daemon=True,
                )
                producer.start()
            try:
                while True:
                    event = self.queue.get()
                    if event is _QUEUE_CANCEL:
                        if self.close_once("cancelled"):
                            yield encode(_completion_event(self.completion_id, "cancelled"))
                        return
                    if event is _QUEUE_DONE:
                        if self.close_once("completed"):
                            yield encode(_completion_event(self.completion_id, "completed"))
                        return
                    if not isinstance(event, dict):
                        continue
                    status = _terminal_status(event)
                    if status is not None:
                        if self.close_once(status):
                            yield encode(event)
                        return
                    yield encode(event)
            finally:
                if not self.is_closed():
                    self.close_once("cancelled")

        return run()

    def _produce(self) -> None:
        terminal_committed = False
        try:
            for event in stream_completion_events(
                completion_id=self.completion_id, resource_path=self.resource_path,
                messages=self.messages, run_options=self.run_options, qa_model=self.model,
                should_stop=lambda: self.cancel_requested,
            ):
                if _terminal_status(event) is not None:
                    terminal_committed = self.commit_terminal_event(event)
                    return
                if not self.commit_event(event):
                    return
        except Exception as exc:
            terminal_committed = self.commit_terminal_event(
                _completion_event(self.completion_id, "failed", error_message=str(exc)),
            )
        finally:
            if not terminal_committed:
                self.commit_done()

    def terminate(self) -> str:
        with self._lock:
            if self.closed or self.terminal_committed:
                return self.status
            if self.cancel_requested:
                return self.status
            self.cancel_requested = True
            self.status = "cancelling"
            if not self._pending_tool_ids:
                self.queue.put(_QUEUE_CANCEL)
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
                self.queue.put(event)
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
            self.queue.put(event)
            return True

    def commit_done(self) -> bool:
        with self._lock:
            if self.cancel_requested or self.closed or self.terminal_committed:
                return False
            self.terminal_committed = True
            self.status = "completed"
            self.queue.put(_QUEUE_DONE)
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


class CompletionManager:
    """进程内多个 document-QA chat completion 的注册表与协调。

    create(...) 装配 路径 + model，构造一个 ActiveCompletion（单 completion 的
    运行时）并注册，返回其 stream() 产出的 SSE 流；terminate / get_status 转发到
    对应 runtime；stream 结束后由托管包装从注册表移除。单实例持有注册表 + 锁，
    应按单进程单实例部署（多 uvicorn worker 不同进程间不共享 cancel 状态）。
    """

    def __init__(self) -> None:
        self._completions: dict[str, ActiveCompletion] = {}
        self._lock = threading.Lock()

    def create(
        self,
        *,
        completion_id: str,
        resource_path: str,
        messages: list[DocumentQaMessage],
        model_config: ModelConfig | None = None,
        run_options: RunOptions | None = None,
    ) -> Iterable[str]:
        if not isinstance(completion_id, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", completion_id) is None:
            raise ValueError("completion_id must be a safe non-empty identifier")
        if not messages:
            raise ValueError("messages must be a non-empty list")
        load_resource(resource_path)
        qa_model = build_qa_model(model_config)
        runtime = ActiveCompletion(completion_id, resource_path, qa_model, messages, run_options)
        with self._lock:
            if completion_id in self._completions:
                raise ValueError("completion_id is already active")
            self._completions[completion_id] = runtime
        return self._managed_stream(runtime)

    def terminate(self, completion_id: str) -> dict[str, Any]:
        with self._lock:
            runtime = self._completions.get(completion_id)
        if runtime is None:
            return {"id": completion_id, "status": "not_found"}
        status = runtime.terminate()
        return {"id": completion_id, "status": status}

    def get_status(self, completion_id: str) -> dict[str, Any] | None:
        with self._lock:
            runtime = self._completions.get(completion_id)
        if runtime is None:
            return None
        return {"id": completion_id, "status": runtime.get_status()}

    def _managed_stream(self, runtime: ActiveCompletion) -> Iterable[str]:
        def run() -> Iterable[str]:
            try:
                yield from runtime.stream()
            finally:
                with self._lock:
                    if self._completions.get(runtime.completion_id) is runtime:
                        self._completions.pop(runtime.completion_id, None)

        return run()


completion_manager = CompletionManager()


def _completion_event(completion_id: str, status: str, **fields: Any) -> dict[str, Any]:
    return {"id": completion_id, "type": f"completion.{status}", "status": status, **fields}


def _terminal_status(event: dict[str, Any]) -> str | None:
    """仅由内部事件的 type 决定终态，不解析 SSE 或正文。"""
    return {
        "completion.completed": "completed",
        "completion.cancelled": "cancelled",
        "completion.failed": "failed",
    }.get(event.get("type"))


__all__ = [
    "ActiveCompletion",
    "CompletionManager",
    "completion_manager",
]
