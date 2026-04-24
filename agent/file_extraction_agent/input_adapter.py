"""file_extraction_agent 的外部输入适配层。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from file_extraction_agent.impl.schemas import (
    ExtractionInput,
    RunOptions,
)
from file_extraction_agent.schemas import (
    NormalizedBlock,
    TaskSpec,
)


TASK_SPECS_DIR = Path(__file__).with_name("task_specs")


class TaskSpecNotFoundError(RuntimeError):
    """task spec 名称无法解析到本地 JSON 时抛出。"""


def build_graph_input(
    *,
    blocks: list[NormalizedBlock],
    markdown: str = "",
    md_list: list[str] | None = None,
    task_spec: TaskSpec | None = None,
    task_spec_name: str | None = None,
    run_options: RunOptions | None = None,
    metadata: dict[str, Any] | None = None,
) -> ExtractionInput:
    """把外部 session 级输入收敛成模块内部统一的 `ExtractionInput`。"""

    resolved_task_spec = _resolve_task_spec(
        task_spec=task_spec,
        task_spec_name=task_spec_name,
    )
    return ExtractionInput(
        blocks=blocks,
        markdown=markdown,
        md_list=md_list or [],
        task_spec=resolved_task_spec,
        options=run_options or RunOptions(),
        metadata=metadata or {},
    )


def _resolve_task_spec(
    *,
    task_spec: TaskSpec | None,
    task_spec_name: str | None,
) -> TaskSpec:
    if task_spec is not None:
        return task_spec
    if task_spec_name is None:
        raise ValueError("task_spec or task_spec_name is required")
    return _load_task_spec_from_name(task_spec_name)


def _load_task_spec_from_name(task_spec_name: str) -> TaskSpec:
    config_path = TASK_SPECS_DIR / f"{task_spec_name}.json"
    try:
        raw_spec = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise TaskSpecNotFoundError(f"task spec not found: {task_spec_name}") from exc
    return TaskSpec.model_validate(raw_spec)
