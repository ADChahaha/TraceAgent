"""service.file_extraction_agent 的外部输入适配层。"""

from __future__ import annotations

from typing import Any

from service.file_extraction_agent.impl.block_ids import validate_block_ids
from service.file_extraction_agent.impl.schemas import (
    ExtractionInput,
    RunOptions,
)
from service.file_extraction_agent.schemas import (
    NormalizedBlock,
    TaskSpec,
)


def build_graph_input(
    *,
    blocks: list[NormalizedBlock],
    markdown: str = "",
    md_list: list[str] | None = None,
    task_spec: TaskSpec | None = None,
    run_options: RunOptions | None = None,
    metadata: dict[str, Any] | None = None,
) -> ExtractionInput:
    """把外部 session 级输入收敛成模块内部统一的 `ExtractionInput`。"""

    resolved_task_spec = _resolve_task_spec(task_spec=task_spec)
    return ExtractionInput(
        blocks=validate_block_ids(blocks),
        markdown=markdown,
        md_list=md_list or [],
        task_spec=resolved_task_spec,
        options=run_options or RunOptions(),
        metadata=metadata or {},
    )


def _resolve_task_spec(*, task_spec: TaskSpec | None) -> TaskSpec:
    if task_spec is not None:
        return task_spec
    raise ValueError("task_spec is required")
