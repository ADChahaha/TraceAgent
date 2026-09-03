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
import shutil
import threading
from typing import Any, Iterable

from service.file_extraction_agent.core.documents import materialize_tree
from service.file_extraction_agent.core.graph import GraphState, build_graph_state
from service.file_extraction_agent.core.loop import run_resolution_stream
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
) -> Iterable[str]:
    emitted = 0
    _append_completion_event(state, "completion.created", status="in_progress")
    _append_source_index_event(state)
    while emitted < len(state.events):
        yield _sse(state.events[emitted])
        emitted += 1

    outcome: Any = {"ok": False, "errors": [{"message": "resolution did not run"}]}
    stopped = False
    try:
        for outcome in run_resolution_stream(state, resolution_model):
            if should_stop is not None and should_stop():
                stopped = True
                break
            while emitted < len(state.events):
                yield _sse(state.events[emitted])
                emitted += 1
    except Exception as exc:
        state.failed_stage = "resolution"
        _append_failure_event(state, exc)
        outcome = {"ok": False, "errors": [{"message": str(exc)}]}

    if stopped:
        _backfill_pending_tool_cancels(state)

    while emitted < len(state.events):
        yield _sse(state.events[emitted])
        emitted += 1

    if stopped:
        _append_completion_event(state, "completion.cancelled", status="cancelled")
    elif _resolution_failed(outcome):
        _append_completion_event(state, "completion.failed", status="failed", error=_failure_reason(outcome))
    else:
        _append_completion_event(state, "completion.completed", status="completed")
    yield _sse(state.events[-1])


def _backfill_pending_tool_cancels(state: GraphState) -> None:
    latest_model_tool_calls: list[dict[str, Any]] = []
    for event in state.events:
        if event.get("type") == "model_message":
            tool_calls = event.get("tool_calls")
            if isinstance(tool_calls, list) and tool_calls:
                latest_model_tool_calls = tool_calls
    if not latest_model_tool_calls:
        return
    fulfilled_tool_refs: set[str] = set()
    for event in state.events:
        if event.get("type") in {"tool_completed", "tool_failed"}:
            tool = event.get("tool")
            if tool is not None:
                fulfilled_tool_refs.add(str(tool))
    for call in latest_model_tool_calls:
        name = str(call.get("name") or "")
        if name and name in fulfilled_tool_refs:
            continue
        state.events.append(
            {
                "seq": state.next_seq,
                "type": "tool_completed",
                "tool": name,
                "args": call.get("args") or {},
                "result": {"ok": False, "errors": [{"message": "tool execution cancelled"}]},
            }
        )
        state.next_seq += 1


def _append_completion_event(
    state: GraphState,
    event_type: str,
    *,
    status: str,
    error: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "seq": state.next_seq,
        "id": state.completion_id,
        "type": event_type,
        "status": status,
    }
    if error:
        payload["error"] = error
    state.next_seq += 1
    state.events.append(payload)


def _append_failure_event(state: GraphState, exc: Exception) -> None:
    state.events.append(
        {
            "seq": state.next_seq,
            "type": "tool_failed",
            "tool": "resolution",
            "result": {"ok": False, "errors": [{"message": str(exc)}]},
        }
    )
    state.next_seq += 1


def _append_source_index_event(state: GraphState) -> None:
    state.events.append(
        {
            "seq": state.next_seq,
            "type": "source_indexed",
            "tool": "source_index",
            "result": {
                "ok": True,
                "workspace_root": str(state.document.root),
                "tree": _file_tree_lines(state.document),
            },
        }
    )
    state.next_seq += 1


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


def _resolution_failed(outcome: Any) -> bool:
    return isinstance(outcome, dict) and outcome.get("ok") is False


def _failure_reason(outcome: Any) -> str:
    if isinstance(outcome, dict):
        errors = outcome.get("errors") or []
        if errors:
            return "; ".join(str(error.get("message", error)) if isinstance(error, dict) else str(error) for error in errors)
    return "resolution failed"


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
) -> GraphState:
    """Validate the strong-typed completion inputs and build the GraphState.

    Raises ValueError when a required field is empty or a list is empty.
    """

    if not isinstance(completion_id, str) or not completion_id.strip():
        raise ValueError("completion_id is required")
    validated_documents = _validate_documents(documents)
    validated_messages = _validate_messages(messages)
    normalized_run_options = _normalize_run_options(run_options)
    resolved_root = _resolve_workspace_root(workspace_root, normalized_run_options)
    document = materialize_tree(validated_documents, Path(resolved_root) / completion_id)
    return build_graph_state(
        completion_id=completion_id,
        document=document,
        messages=validated_messages,
        run_options=normalized_run_options,
    )


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
      -> 循环 queue.get() 取事件：普通事件 yield；_QUEUE_CANCEL/_QUEUE_DONE/终态事件
         则 close_once 后收口并结束
      -> finally 确保终态唯一并清理 workspace（注册表移除由 CompletionManager 托管）

    _produce()
      -> 后台线程目标，循环 run_completion_graph_stream(state, model) 产 SSE 事件
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
        self._state_lock = getattr(state, "events_lock", None) or threading.Lock()
        self.queue: queue.Queue[str | object] = queue.Queue()

    def stream(self) -> Iterable[str]:
        def run() -> Iterable[str]:
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
                            yield _completion_cancelled_event(self.completion_id)
                        return
                    if event is _QUEUE_DONE:
                        if self.close_once("completed"):
                            yield _completion_completed_event(self.completion_id)
                        return
                    if not isinstance(event, str):
                        continue
                    if _is_terminal_event(event):
                        if self.close_once(_terminal_status(event)):
                            yield event
                        return
                    yield event
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
                if _is_terminal_event(event):
                    status = _terminal_status(event)
                    terminal_committed = self.commit_terminal_event(event, status)
                    return
                if not self.commit_event(event):
                    return
        except Exception as exc:
            terminal_committed = self.commit_terminal_event(
                _completion_failed_event(self.completion_id, str(exc)),
                "failed",
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
            with self._state_lock:
                batch_active = getattr(self.state, "tool_batch_active", False)
            if not batch_active:
                self.queue.put(_QUEUE_CANCEL)
            else:
                self._cancel_deferred = True
            return self.status

    def get_status(self) -> str:
        return self.status

    def commit_events(self, events: Iterable[str]) -> bool:
        with self._lock:
            if self.closed or self.terminal_committed:
                return False
            if self.cancel_requested and not self._cancel_deferred:
                return False
            active_events = list(events)
            for event in active_events:
                if _is_terminal_event(event):
                    continue
                self.queue.put(event)
            return True

    def commit_event(self, event: str) -> bool:
        return self.commit_events([event])

    def commit_terminal_event(self, event: str, status: str) -> bool:
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
    ) -> Iterable[str]:
        state = prepare_completion_state(
            completion_id=completion_id,
            documents=documents,
            messages=messages,
            run_options=run_options,
        )
        resolution_model = build_resolution_model(model_config)
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
    shutil.rmtree(root, ignore_errors=True)


def _completion_cancelled_event(completion_id: str) -> str:
    return (
        "event: completion.cancelled\n"
        f'data: {{"id":"{completion_id}","type":"completion.cancelled","status":"cancelled"}}\n\n'
    )


def _completion_completed_event(completion_id: str) -> str:
    return (
        "event: completion.completed\n"
        f'data: {{"id":"{completion_id}","type":"completion.completed","status":"completed"}}\n\n'
    )


def _completion_failed_event(completion_id: str, error_message: str) -> str:
    escaped = error_message.replace("\\", "\\\\").replace('"', '\\"')
    return (
        "event: completion.failed\n"
        f'data: {{"id":"{completion_id}","type":"completion.failed","status":"failed","error_message":"{escaped}"}}\n\n'
    )


def _is_terminal_event(event: str) -> bool:
    return (
        "event: completion.completed" in event
        or "event: completion.cancelled" in event
        or "event: completion.failed" in event
    )


def _terminal_status(event: str) -> str:
    if "event: completion.cancelled" in event:
        return "cancelled"
    if "event: completion.failed" in event:
        return "failed"
    return "completed"


__all__ = [
    "ActiveCompletion",
    "CompletionManager",
    "completion_manager",
    "prepare_completion_state",
]
