"""Completion lifecycle manager for document-QA chat completions.

`CompletionManager` 用 create / terminate 统一管理一个 completion 的完整生命
周期：入参准备（`prepare_completion_state`）、注册 runtime、启动 producer、对
外产出 SSE 流、取消与收尾。真正的 agent loop 在 `impl/graph.py`，本模块只是
生命周期调度层。模块级 `create_completion_stream` / `cancel_completion` 是对
进程内单例 `completion_manager` 的薄委托，供 HTTP 路由和既有调用方使用。
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import queue
import shutil
import threading
from typing import Any, Iterable

from service.file_extraction_agent.impl.graph import run_completion_graph_stream
from service.file_extraction_agent.impl.html_index import materialize_tree
from service.file_extraction_agent.impl.html_state import GraphState, build_graph_state
from service.file_extraction_agent.impl.model_factory import ChatModelFallbackChain, build_resolution_model
from service.file_extraction_agent.schemas import DocumentQaMessage, InputDocument, ModelConfig, RunOptions


_QUEUE_CANCEL = object()
_QUEUE_DONE = object()

DEFAULT_WORKSPACE_ROOT = os.getenv(
    "FILE_EXTRACTION_AGENT_WORKSPACE_ROOT",
    str(Path(__file__).resolve().parents[2] / "data" / "qa_workspace"),
)


@dataclass
class ActiveCompletion:
    completion_id: str
    status: str = "in_progress"
    cancel_requested: bool = False
    closed: bool = False
    terminal_committed: bool = False

    def __post_init__(self) -> None:
        self._lock = threading.Lock()
        self.queue: queue.Queue[str | object] = queue.Queue()

    def commit_events(self, events: Iterable[str]) -> bool:
        with self._lock:
            if self.cancel_requested or self.closed or self.terminal_committed:
                return False
            for event in events:
                self.queue.put(event)
            return True

    def commit_event(self, event: str) -> bool:
        return self.commit_events([event])

    def commit_terminal_event(self, event: str, status: str) -> bool:
        with self._lock:
            if self.cancel_requested or self.closed or self.terminal_committed:
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

    def request_cancel(self) -> str:
        with self._lock:
            if self.closed or self.terminal_committed:
                return self.status
            if self.cancel_requested:
                return self.status
            self.cancel_requested = True
            self.status = "cancelling"
            self.queue.put(_QUEUE_CANCEL)
            return self.status

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


def prepare_completion_state(
    *,
    completion_id: str,
    documents: list[InputDocument],
    messages: list[DocumentQaMessage],
    run_options: RunOptions | None = None,
    workspace_root: str | Path | None = None,
) -> GraphState:
    """Validate the strong-typed completion inputs and build the GraphState.

    Raises ValueError when a required field is empty, a list is empty, or
    max_tool_calls is not positive.
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
    if options.max_tool_calls <= 0:
        raise ValueError("max_tool_calls must be positive")
    return options


def _resolve_workspace_root(explicit: str | Path | None, run_options: RunOptions) -> Path:
    if explicit is not None:
        return Path(explicit)
    if run_options.workspace_root:
        return Path(run_options.workspace_root)
    return Path(DEFAULT_WORKSPACE_ROOT)


class CompletionManager:
    """进程内管理 document-QA chat completion 生命周期。

    create(...) 校验强类型入参、落盘文件树、注册 runtime，启动 producer 线程并
    返回 SSE 流；terminate(completion_id) 设置取消状态并唤醒 consumer；
    get_status(...) 查询当前状态。单个实例持有本进程内的 completion 注册表，
    因此应按单进程单实例部署（多 uvicorn worker 不同进程间不共享 cancel 状态）。

    生命周期分为 producer / consumer 两半，靠 `ActiveCompletion.queue` + 锁协作：

    create(completion_id + documents + messages + model_config + run_options)
      -> prepare_completion_state(...)（校验失败抛 ValueError）
      -> build_resolution_model(model_config) -> ChatModelFallbackChain
      -> 注册 ActiveCompletion 到 _completions
      -> 返回 _stream(...) SSE 迭代器（首次迭代才启动 producer）

    _produce（后台线程）
      -> 循环 run_completion_graph_stream(state, model) 产 SSE event
      -> 每条用 runtime.commit_event / commit_terminal_event 投进 queue

    _stream（consumer）
      -> 首次迭代启动 producer；每次 next() = queue.get() 取一个事件 yield
      -> 收到 _QUEUE_CANCEL / _QUEUE_DONE / 终态事件时 close_once 后收口
      -> finally 关闭 runtime、从注册表移除、清理 workspace

    terminate(completion_id)
      -> request_cancel() 设置取消状态并放入 cancel sentinel
      -> 找不到返回 {"status": "not_found"}
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
        runtime = ActiveCompletion(completion_id=completion_id)
        with self._lock:
            self._completions[completion_id] = runtime
        return self._stream(state=state, resolution_model=resolution_model, runtime=runtime)

    def terminate(self, completion_id: str) -> dict[str, Any]:
        with self._lock:
            runtime = self._completions.get(completion_id)
        if runtime is None:
            return {"id": completion_id, "status": "not_found"}
        status = runtime.request_cancel()
        return {"id": completion_id, "status": status}

    def get_status(self, completion_id: str) -> dict[str, Any] | None:
        with self._lock:
            runtime = self._completions.get(completion_id)
        if runtime is None:
            return None
        return {"id": completion_id, "status": runtime.status}

    def _stream(
        self,
        *,
        state: GraphState,
        resolution_model: ChatModelFallbackChain,
        runtime: ActiveCompletion,
    ) -> Iterable[str]:
        def stream() -> Iterable[str]:
            if not runtime.should_cancel():
                producer = threading.Thread(
                    target=self._produce,
                    kwargs={
                        "state": state,
                        "resolution_model": resolution_model,
                        "runtime": runtime,
                    },
                    name=f"qa-completion-{runtime.completion_id}",
                    daemon=True,
                )
                producer.start()
            try:
                while True:
                    event = runtime.queue.get()
                    if event is _QUEUE_CANCEL:
                        if runtime.close_once("cancelled"):
                            yield _completion_cancelled_event(runtime.completion_id)
                        return
                    if event is _QUEUE_DONE:
                        if runtime.close_once("completed"):
                            yield _completion_completed_event(runtime.completion_id)
                        return
                    if not isinstance(event, str):
                        continue
                    if _is_terminal_event(event):
                        if runtime.close_once(_terminal_status(event)):
                            yield event
                        return
                    yield event
            finally:
                if not runtime.is_closed():
                    runtime.close_once("cancelled")
                with self._lock:
                    if self._completions.get(runtime.completion_id) is runtime:
                        self._completions.pop(runtime.completion_id, None)
                _cleanup_workspace(state)

        return stream()

    def _produce(
        self,
        *,
        state: GraphState,
        resolution_model: ChatModelFallbackChain,
        runtime: ActiveCompletion,
    ) -> None:
        terminal_committed = False
        try:
            for event in run_completion_graph_stream(state, resolution_model):
                if _is_terminal_event(event):
                    status = _terminal_status(event)
                    terminal_committed = runtime.commit_terminal_event(event, status)
                    return
                if not runtime.commit_event(event):
                    return
        except Exception as exc:
            terminal_committed = runtime.commit_terminal_event(
                _completion_failed_event(runtime.completion_id, str(exc)),
                "failed",
            )
        finally:
            if not terminal_committed:
                runtime.commit_done()


completion_manager = CompletionManager()


def create_completion_stream(
    *,
    completion_id: str,
    documents: list[InputDocument],
    messages: list[DocumentQaMessage],
    model_config: ModelConfig | None = None,
    run_options: RunOptions | None = None,
) -> Iterable[str]:
    return completion_manager.create(
        completion_id=completion_id,
        documents=documents,
        messages=messages,
        model_config=model_config,
        run_options=run_options,
    )


def cancel_completion(completion_id: str) -> dict[str, Any]:
    return completion_manager.terminate(completion_id)


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
    "CompletionManager",
    "completion_manager",
    "create_completion_stream",
    "cancel_completion",
    "prepare_completion_state",
]
