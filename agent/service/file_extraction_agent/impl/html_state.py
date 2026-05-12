"""Internal run state for the HTML extraction flow."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from service.file_extraction_agent.impl.html_index import HtmlDocument
from service.file_extraction_agent.schemas import RunOptions, TaskSpec


@dataclass
class HtmlExtractionInput:
    html: str
    task_spec: TaskSpec
    document: HtmlDocument
    run_options: RunOptions = field(default_factory=RunOptions)


@dataclass
class GraphState:
    extraction_input: HtmlExtractionInput
    document: HtmlDocument
    task_spec: TaskSpec
    run_options: RunOptions
    document_scan_model: Any = None
    plan_statuses: dict[int, dict[str, Any]] = field(default_factory=dict)
    field_states: dict[str, dict[str, Any]] = field(default_factory=dict)
    actions: list[dict[str, Any]] = field(default_factory=list)
    observed_evidence_ids: set[str] = field(default_factory=set)
    inline_evidence_by_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    failed_stage: str | None = None


def build_graph_state(extraction_input: HtmlExtractionInput) -> GraphState:
    return GraphState(
        extraction_input=extraction_input,
        document=extraction_input.document,
        task_spec=extraction_input.task_spec,
        run_options=extraction_input.run_options,
    )


__all__ = ["HtmlExtractionInput", "GraphState", "build_graph_state"]
