"""Completion lifecycle manager for document-QA chat completions.

`ActiveCompletion` 是单个 completion 的完整运行时：持有该 completion 专属的
state（GraphState）、resolution_model、事件通道 queue 与同步锁，并自己启动
producer 线程、消费队列产出 SSE、决定唯一终态、清理落盘目录。`CompletionManager`
只负责多个 completion 的注册表与 create/terminate/status 转发。公开入口是进程内
单例 `completion_manager`，HTTP 路由等调用方直接 `completion_manager.create(...)` /
`completion_manager.terminate(...)`。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, is_dataclass
from pathlib import Path
import queue
import re
import shutil
import threading
from typing import Any, Iterable

from langchain_core.messages import AIMessage, ToolMessage

from service.file_extraction_agent.core.documents import materialize_tree
from service.file_extraction_agent.core.graph import GraphState, build_graph_state

from service.file_extraction_agent.core.loop import run_resolution_stream, _message_stop_signal, _terminal_stop_signals
from service.file_extraction_agent.core.model import ChatModelFallbackChain, build_resolution_model
from service.file_extraction_agent.schemas import DocumentQaMessage, InputDocument, ModelConfig, RunOptions


_QUEUE_CANCEL = object()
_QUEUE_DONE = object()

DEFAULT_WORKSPACE_ROOT = os.getenv(
    "FILE_EXTRACTION_AGENT_WORKSPACE_ROOT",
    str(Path(__file__).resolve().parents[2] / "data" / "qa_workspace"),
)


def run_completion_graph_stream(
    state: GraphState,
    resolution_model: ChatModelFallbackChain | None = None,
    *,
    should_stop=None,
) -> Iterable[dict[str, Any]]:
    """消息流 → 模型/调度/结果事件；按 call ID 配对，批次后取消，异常补结果后失败。"""
    pending: dict[str, dict[str, Any]] = {}

    def stopped() -> bool:
        return should_stop is not None and should_stop()

    yield {"id": state.completion_id, "type": "completion.created", "status": "in_progress"}
    yield {"type": "source_indexed", "tool": "source_index", "result": {
        "ok": True, "workspace_root": str(state.document.root), "tree": _file_tree_lines(state.document),
    }}
    messages = iter(run_resolution_stream(state, resolution_model))
    try:
        while pending or not stopped():
            try:
                message = next(messages)
            except StopIteration:
                if pending:
                    raise RuntimeError("message stream ended with pending tool calls")
                break
            if isinstance(message, AIMessage):
                if pending:
                    raise ValueError("model message arrived before tool replies")
                if stopped():
                    break
                calls = {call["id"]: call for call in message.tool_calls}
                if any(not call_id for call_id in calls) or len(calls) != len(message.tool_calls):
                    raise ValueError("tool calls require unique non-empty IDs")
                pending.update(calls)
                yield _model_message_event(message)
                for call in pending.values():
                    yield {"type": "tool_started", "tool": call["name"], "args": call["args"], "tool_call_id": call["id"]}
            elif isinstance(message, ToolMessage):
                call = pending.pop(message.tool_call_id, None)
                if call is None:
                    raise ValueError(f"unpaired tool reply: {message.tool_call_id}")
                yield _tool_message_event(message, call)
            else:
                raise TypeError(f"unexpected message type: {type(message).__name__}")
    except Exception as exc:
        for call in pending.values():
            result = {"ok": False, "errors": [{"message": str(exc)}]}
            yield _tool_message_event(ToolMessage(content=json.dumps(result), artifact=result,
                status="error", tool_call_id=call["id"]), call)
        yield {"type": "tool_failed", "tool": "resolution", "result": {"ok": False, "errors": [{"message": str(exc)}]}}
        status = "cancelled" if stopped() else "failed"
        yield _completion_event(state.completion_id, status, error=str(exc))
        return
    finally:
        close = getattr(messages, "close", None)
        if close is not None:
            close()
    yield _completion_event(state.completion_id, "cancelled" if stopped() else "completed")


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



def prepare_completion_state(
    *,
    completion_id: str,
    documents: list[InputDocument],
    messages: list[DocumentQaMessage],
    run_options: RunOptions | None = None,
    workspace_root: str | Path | None = None,
    task_id: str | None = None,
) -> GraphState:
    """Validate the strong-typed completion inputs and build the GraphState.

    Raises ValueError when a required field is empty or a list is empty.
    """

    if not isinstance(completion_id, str) or not completion_id.strip():
        raise ValueError("completion_id is required")
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", completion_id) is None:
        raise ValueError("completion_id must be a safe identifier (letters, digits, underscores or hyphens)")
    if task_id is not None and (not isinstance(task_id, str) or not task_id.strip()):
        raise ValueError("task_id must be a non-empty string")
    validated_documents = _validate_documents(documents)
    validated_messages = _validate_messages(messages)
    normalized_run_options = _normalize_run_options(run_options)
    resolved_root = _resolve_workspace_root(workspace_root, normalized_run_options).resolve()
    run_root = resolved_root / completion_id
    if run_root.resolve().parent != resolved_root:
        raise ValueError("workspace escapes its parent directory")
    try:
        run_root.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise ValueError("completion workspace already exists") from exc
    try:
        document = materialize_tree(validated_documents, run_root)
    except Exception:
        shutil.rmtree(run_root, ignore_errors=True)
        raise
    state = build_graph_state(
        completion_id=completion_id,
        document=document,
        messages=validated_messages,
        run_options=normalized_run_options,
    )
    state.task_id = task_id
    state.workspace_parent = resolved_root
    return state


def _validate_documents(documents: list[InputDocument]) -> list[InputDocument]:
    if not documents:
        raise ValueError("documents must be a non-empty list")
    for index, document in enumerate(documents, start=1):
        if not document.filename.strip():
            raise ValueError(f"documents[{index}].filename is required")
        if not document.html.strip():
            raise ValueError(f"documents[{index}].html must be a non-empty string")
    return documents


def _validate_messages(messages: list[DocumentQaMessage]) -> list[DocumentQaMessage]:
    if not messages:
        raise ValueError("messages must be a non-empty list")
    return messages


def _normalize_run_options(run_options: RunOptions | None) -> RunOptions:
    options = run_options if run_options is not None else RunOptions()
    return options


def _resolve_workspace_root(explicit: str | Path | None, run_options: RunOptions) -> Path:
    if explicit is not None:
        return Path(explicit)
    if run_options.workspace_root:
        return Path(run_options.workspace_root)
    return Path(DEFAULT_WORKSPACE_ROOT)


class ActiveCompletion:
    """单个 document-QA chat completion 的运行时。

    持有该 completion 专属的 state、resolution_model、事件通道 queue 与同步锁。
    它自己完成生产、消费与收尾：

    stream()
      -> 首次迭代时启动 producer 线程（target=_produce）
      -> 循环 queue.get() 取事件：普通事件编码为 SSE 后 yield；_QUEUE_CANCEL/_QUEUE_DONE/终态事件
         则 close_once 后收口并结束
      -> finally 确保终态唯一并清理 workspace（注册表移除由 CompletionManager 托管）

    _produce()
      -> 后台线程目标，循环 run_completion_graph_stream(state, model) 产事件字典
      -> 用 commit_* / commit_terminal_event 投进 queue；异常投 completion.failed；
         兜底 commit_done

    terminate() / get_status()：取消 / 查询状态。

    事件通道 + 终态裁定由 _lock 线性化：cancel 前已提交的事件按 FIFO 先发，cancel
    之后的新事件被拒收；terminal 只提交一次；close_once 保证终态唯一。
    """

    def __init__(self, completion_id: str, state: GraphState, resolution_model: ChatModelFallbackChain) -> None:
        self.completion_id = completion_id
        self.state = state
        self.model = resolution_model
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
                _cleanup_workspace(self.state)

        return run()

    def _produce(self) -> None:
        terminal_committed = False
        try:
            for event in run_completion_graph_stream(
                self.state,
                self.model,
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

    create(...) 装配 state + model，构造一个 ActiveCompletion（单 completion 的
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
        documents: list[InputDocument],
        messages: list[DocumentQaMessage],
        model_config: ModelConfig | None = None,
        run_options: RunOptions | None = None,
        task_id: str | None = None,
    ) -> Iterable[str]:
        state = prepare_completion_state(
            completion_id=completion_id,
            documents=documents,
            messages=messages,
            run_options=run_options,
            task_id=task_id,
        )
        try:
            resolution_model = build_resolution_model(model_config)
        except Exception:
            _cleanup_workspace(state)
            raise
        runtime = ActiveCompletion(completion_id, state, resolution_model)
        with self._lock:
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


def _cleanup_workspace(state: GraphState) -> None:
    root = state.document.root
    parent = state.workspace_parent
    if parent is None or root.is_symlink() or root.resolve().parent != parent.resolve():
        raise ValueError("workspace is outside its owned parent directory")
    shutil.rmtree(root, ignore_errors=True)


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
    "prepare_completion_state",
]
