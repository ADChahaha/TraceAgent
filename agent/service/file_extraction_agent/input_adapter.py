"""Adapt public HTML extraction inputs into internal graph input."""

from __future__ import annotations

from typing import Any

from service.file_extraction_agent.impl.html_index import build_html_document
from service.file_extraction_agent.impl.html_state import HtmlExtractionInput
from service.file_extraction_agent.schemas import FieldDefinition, RunOptions, TaskSpec


def build_graph_input(
    *,
    html: str,
    task_spec: Any,
    run_options: Any = None,
) -> HtmlExtractionInput:
    if not isinstance(html, str) or not html.strip():
        raise ValueError("html must be a non-empty string")
    normalized_task_spec = normalize_task_spec(task_spec)
    normalized_run_options = normalize_run_options(run_options)
    document = build_html_document(html)
    return HtmlExtractionInput(
        html=html,
        task_spec=normalized_task_spec,
        document=document,
        run_options=normalized_run_options,
    )


def normalize_task_spec(task_spec: Any) -> TaskSpec:
    if task_spec is None:
        raise ValueError("task_spec is required")
    if isinstance(task_spec, TaskSpec):
        spec = task_spec
    elif isinstance(task_spec, dict):
        spec = TaskSpec(**task_spec)
    else:
        fields = getattr(task_spec, "fields", None)
        instructions = getattr(task_spec, "instructions", None)
        spec = TaskSpec(fields=fields, instructions=instructions)

    if not spec.fields:
        raise ValueError("task_spec.fields must be non-empty")
    for field_def in spec.fields:
        if not isinstance(field_def, FieldDefinition):
            raise ValueError("task_spec fields must be FieldDefinition-compatible")
        if not field_def.name:
            raise ValueError("field name is required")
    return spec


def normalize_run_options(run_options: Any) -> RunOptions:
    if run_options is None:
        options = RunOptions()
    elif isinstance(run_options, RunOptions):
        options = run_options
    elif isinstance(run_options, dict):
        options = RunOptions(**run_options)
    else:
        options = RunOptions(max_tool_calls=getattr(run_options, "max_tool_calls", 20))
    if options.max_tool_calls <= 0:
        raise ValueError("max_tool_calls must be positive")
    return options


__all__ = ["build_graph_input", "normalize_task_spec", "normalize_run_options"]
