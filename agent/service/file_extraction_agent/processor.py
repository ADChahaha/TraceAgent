"""Public streaming document QA completion entrypoint."""

from __future__ import annotations

from dataclasses import dataclass
import queue
import threading
from typing import Any, Iterable

from service.file_extraction_agent.impl import graph as completion_graph
from service.file_extraction_agent.impl.model_factory import build_resolution_model
from service.file_extraction_agent.input_adapter import build_completion_input
from service.file_extraction_agent.schemas import ModelConfig, RunOptions


_QUEUE_CANCEL = object()
_QUEUE_DONE = object()


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


_ACTIVE_COMPLETIONS: dict[str, ActiveCompletion] = {}
_ACTIVE_COMPLETIONS_LOCK = threading.Lock()


def create_completion_stream(
    *,
    completion_id: str,
    documents: list[Any],
    messages: list[Any],
    memory: Any = None,
    model_config: ModelConfig | dict | None = None,
    run_options: RunOptions | dict | None = None,
) -> Iterable[str]:
    completion_input = build_completion_input(
        completion_id=completion_id,
        documents=documents,
        messages=messages,
        memory=memory,
        run_options=run_options,
    )
    resolution_model = build_resolution_model(model_config)
    runtime = ActiveCompletion(completion_id=completion_id)
    with _ACTIVE_COMPLETIONS_LOCK:
        _ACTIVE_COMPLETIONS[completion_id] = runtime

    def stream() -> Iterable[str]:
        if not runtime.should_cancel():
            producer = threading.Thread(
                target=_produce_completion_events,
                kwargs={
                    "completion_input": completion_input,
                    "resolution_model": resolution_model,
                    "runtime": runtime,
                },
                name=f"qa-completion-{completion_id}",
                daemon=True,
            )
            producer.start()
        try:
            while True:
                event = runtime.queue.get()
                if event is _QUEUE_CANCEL:
                    if runtime.close_once("cancelled"):
                        yield _completion_cancelled_event(completion_id)
                    return
                if event is _QUEUE_DONE:
                    if runtime.close_once("completed"):
                        yield _completion_completed_event(completion_id)
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
            with _ACTIVE_COMPLETIONS_LOCK:
                if _ACTIVE_COMPLETIONS.get(completion_id) is runtime:
                    _ACTIVE_COMPLETIONS.pop(completion_id, None)

    return stream()


def _produce_completion_events(
    *,
    completion_input: Any,
    resolution_model: Any,
    runtime: ActiveCompletion,
) -> None:
    terminal_committed = False
    try:
        for event in run_completion_graph_stream(completion_input, resolution_model):
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


def run_completion_graph_stream(completion_input: Any, resolution_model: Any) -> Iterable[str]:
    return completion_graph.run_completion_graph_stream(completion_input, resolution_model=resolution_model)


def cancel_completion(completion_id: str) -> dict[str, Any]:
    with _ACTIVE_COMPLETIONS_LOCK:
        runtime = _ACTIVE_COMPLETIONS.get(completion_id)
    if runtime is None:
        return {"id": completion_id, "status": "not_found"}
    status = runtime.request_cancel()
    return {"id": completion_id, "status": status}


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


__all__ = ["create_completion_stream", "cancel_completion", "run_completion_graph_stream"]
