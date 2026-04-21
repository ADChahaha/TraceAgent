"""file_extraction_agent 的外部输入适配层。

实现步骤：

```text
调用方传入 session_id、documents，可选 task_spec 或 task_spec_name
  -> 先校验 task_spec 与 task_spec_name 至少有一个可用
  -> 如果显式传了 task_spec，就直接使用
  -> 如果只传了 task_spec_name，就从 task_specs/*.json 加载并校验成 TaskSpec
  -> 再把 session_id、documents、task_spec、run_config、metadata 收敛成 GraphInput
  -> 返回给 processor 继续执行抽取流程
```
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from file_extraction_agent.schemas import (
    GraphInput,
    NormalizedDocument,
    RunConfig,
    TaskSpec,
)


TASK_SPECS_DIR = Path(__file__).with_name("task_specs")


class TaskSpecNotFoundError(RuntimeError):
    """task spec 名称无法解析到本地 JSON 时抛出。"""


def build_graph_input(
    *,
    session_id: str,
    documents: list[NormalizedDocument],
    task_spec: TaskSpec | None = None,
    task_spec_name: str | None = None,
    run_config: RunConfig | None = None,
    metadata: dict[str, Any] | None = None,
) -> GraphInput:
    """把外部 session 级输入收敛成模块内部统一的 GraphInput。"""

    resolved_task_spec = _resolve_task_spec(
        task_spec=task_spec,
        task_spec_name=task_spec_name,
    )
    return GraphInput(
        session_id=session_id,
        documents=documents,
        task_spec=resolved_task_spec,
        run_config=run_config or RunConfig(),
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

