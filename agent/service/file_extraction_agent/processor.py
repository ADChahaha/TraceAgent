"""Public extraction entrypoint."""

from __future__ import annotations

from typing import Any

from service.file_extraction_agent.impl import graph as extraction_graph
from service.file_extraction_agent.impl.model_factory import build_stage_models
from service.file_extraction_agent.input_adapter import build_graph_input
from service.file_extraction_agent.schemas import ModelConfig, RunOptions, TaskSpec


def run_extraction_graph(extraction_input: Any, broad_model: Any, resolution_model: Any) -> Any:
    return extraction_graph.run_extraction_graph(extraction_input, broad_model, resolution_model)


def extract(
    *,
    html: str,
    task_spec: TaskSpec | dict,
    model_config: ModelConfig | dict | None = None,
    run_options: RunOptions | dict | None = None,
) -> Any:
    extraction_input = build_graph_input(
        html=html,
        task_spec=task_spec,
        run_options=run_options,
    )
    broad_model, resolution_model = build_stage_models(model_config)
    return run_extraction_graph(extraction_input, broad_model, resolution_model)


__all__ = ["extract", "run_extraction_graph"]
