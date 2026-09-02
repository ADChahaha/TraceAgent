"""Internal run state for the document QA completion flow."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from service.file_extraction_agent.impl.html_index import DocumentFileTree
from service.file_extraction_agent.schemas import DocumentQaMessage, RunOptions


@dataclass
class GraphState:
    completion_id: str
    document: DocumentFileTree
    messages: list[DocumentQaMessage]
    run_options: RunOptions
    actions: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    current_model_content: str = ""
    next_seq: int = 1
    failed_stage: str | None = None


def build_graph_state(
    *,
    completion_id: str,
    document: DocumentFileTree,
    messages: list[DocumentQaMessage],
    run_options: RunOptions,
) -> GraphState:
    return GraphState(
        completion_id=completion_id,
        document=document,
        messages=messages,
        run_options=run_options,
    )


__all__ = ["GraphState", "build_graph_state"]
