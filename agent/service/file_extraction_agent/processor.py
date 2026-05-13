"""Public streaming extraction entrypoint."""

from __future__ import annotations

from typing import Any, Iterable

from service.file_extraction_agent.impl import graph as extraction_graph
from service.file_extraction_agent.impl.model_factory import build_resolution_model
from service.file_extraction_agent.input_adapter import build_graph_input
from service.file_extraction_agent.schemas import ModelConfig, RunOptions, TaskSpec


def run_extraction_graph_stream(extraction_input: Any, resolution_model: Any) -> Iterable[str]:
    return extraction_graph.run_extraction_graph_stream(extraction_input, resolution_model=resolution_model)


def extract_stream(
    *,
    documents: list[Any],
    task_spec: TaskSpec | dict,
    model_config: ModelConfig | dict | None = None,
    run_options: RunOptions | dict | None = None,
) -> Iterable[str]:
    extraction_input = build_graph_input(
        documents=documents,
        task_spec=task_spec,
        run_options=run_options,
    )
    resolution_model = build_resolution_model(model_config)
    return run_extraction_graph_stream(extraction_input, resolution_model)


__all__ = ["extract_stream", "run_extraction_graph_stream"]
