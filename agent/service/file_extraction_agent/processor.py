"""Public streaming document QA completion entrypoint."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from service.file_extraction_agent.impl import graph as completion_graph
from service.file_extraction_agent.impl.model_factory import build_resolution_model
from service.file_extraction_agent.input_adapter import build_completion_input
from service.file_extraction_agent.schemas import ModelConfig, RunOptions


@dataclass
class ActiveCompletion:
    completion_id: str
    status: str = "in_progress"
    cancel_requested: bool = False


_ACTIVE_COMPLETIONS: dict[str, ActiveCompletion] = {}


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
    _ACTIVE_COMPLETIONS[completion_id] = runtime

    def stream() -> Iterable[str]:
        try:
            for event in run_completion_graph_stream(completion_input, resolution_model):
                if runtime.cancel_requested:
                    runtime.status = "cancelled"
                    yield _completion_cancelled_event(completion_id)
                    return
                yield event
            runtime.status = "completed"
        finally:
            _ACTIVE_COMPLETIONS.pop(completion_id, None)

    return stream()


def run_completion_graph_stream(completion_input: Any, resolution_model: Any) -> Iterable[str]:
    return completion_graph.run_completion_graph_stream(completion_input, resolution_model=resolution_model)


def cancel_completion(completion_id: str) -> dict[str, Any]:
    runtime = _ACTIVE_COMPLETIONS.get(completion_id)
    if runtime is None:
        return {"id": completion_id, "status": "not_found"}
    if runtime.status in {"completed", "cancelled", "failed"}:
        return {"id": completion_id, "status": runtime.status}
    runtime.cancel_requested = True
    runtime.status = "cancelling"
    return {"id": completion_id, "status": "cancelling"}


def _completion_cancelled_event(completion_id: str) -> str:
    return (
        "event: completion.cancelled\n"
        f'data: {{"id":"{completion_id}","type":"completion.cancelled","status":"cancelled"}}\n\n'
    )


__all__ = ["create_completion_stream", "cancel_completion", "run_completion_graph_stream"]
