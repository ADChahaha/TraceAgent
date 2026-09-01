"""Internal run state for the document QA completion flow."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from service.file_extraction_agent.impl.html_index import DocumentFileTree
from service.file_extraction_agent.schemas import (
    DocumentQaMessage,
    InputDocument,
    RunOptions,
)


@dataclass
class DocumentQaCompletionInput:
    completion_id: str
    documents: list[InputDocument]
    messages: list[DocumentQaMessage]
    document: DocumentFileTree
    run_options: RunOptions = field(default_factory=RunOptions)


@dataclass
class GraphState:
    completion_input: DocumentQaCompletionInput
    completion_id: str
    document: DocumentFileTree
    messages: list[DocumentQaMessage]
    run_options: RunOptions
    actions: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    current_model_content: str = ""
    next_seq: int = 1
    failed_stage: str | None = None


def build_graph_state(completion_input: DocumentQaCompletionInput) -> GraphState:
    return GraphState(
        completion_input=completion_input,
        completion_id=completion_input.completion_id,
        document=completion_input.document,
        messages=completion_input.messages,
        run_options=completion_input.run_options,
    )


__all__ = ["DocumentQaCompletionInput", "GraphState", "build_graph_state"]
