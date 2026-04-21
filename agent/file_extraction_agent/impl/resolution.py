"""file_extraction_agent 的 field resolution 节点。

实现步骤：

```text
GraphState(graph_input=..., broad_output=...)
  -> run_resolution(...) 先确认 state.broad_output 已存在
  -> resolve_fields(...) 按 graph_input.task_spec.fields 建立最终输出顺序
  -> 从 broad_output.fields 建 field_name -> field_output 索引
  -> 每个字段先做候选去重
  -> 空候选输出 failed；唯一候选输出 resolved；多个不同候选输出 failed
  -> 把整批 ResolvedFieldOutput 写回 state.resolved_fields
  -> 返回同一个 GraphState，交给后续汇总层继续使用
```
"""

from __future__ import annotations

from typing import Any

from file_extraction_agent.impl.state import GraphState
from file_extraction_agent.schemas import (
    BroadExtractionFieldOutput,
    BroadExtractionOutput,
    ResolvedFieldOutput,
    TaskSpec,
)


def run_resolution(*, state: GraphState) -> GraphState:
    """执行第二阶段字段定案，并把结果写回图状态。"""

    if state.broad_output is None:
        raise ValueError("resolution requires broad_output before resolving fields")

    state.resolved_fields = resolve_fields(
        task_spec=state.graph_input.task_spec,
        broad_output=state.broad_output,
    )
    return state


def resolve_fields(
    *,
    task_spec: TaskSpec,
    broad_output: BroadExtractionOutput,
) -> list[ResolvedFieldOutput]:
    """按 task spec 顺序把 broad extraction 结果收口成最终字段结果。"""

    broad_output_by_field = {
        field_output.field_name: field_output for field_output in broad_output.fields
    }
    return [
        resolve_single_field(
            field_name=field.field_name,
            field_output=broad_output_by_field.get(field.field_name),
        )
        for field in task_spec.fields
    ]


def resolve_single_field(
    *,
    field_name: str,
    field_output: BroadExtractionFieldOutput | None,
) -> ResolvedFieldOutput:
    """把单字段候选结果收口成 resolved 或 failed。"""

    if field_output is None or not field_output.candidate_values:
        return ResolvedFieldOutput(
            field_name=field_name,
            status="failed",
            used_field_outputs=[field_name] if field_output is not None else [],
            extra_lookup_used=False,
            failure_reason="未找到可用候选值",
        )

    normalized_candidates = _deduplicate_candidates(field_output.candidate_values)
    if len(normalized_candidates) == 1:
        return ResolvedFieldOutput(
            field_name=field_name,
            status="resolved",
            final_value=normalized_candidates[0],
            used_field_outputs=[field_name],
            extra_lookup_used=False,
            reason="候选值唯一，可直接定案",
        )

    return ResolvedFieldOutput(
        field_name=field_name,
        status="failed",
        used_field_outputs=[field_name],
        extra_lookup_used=False,
        failure_reason="候选值冲突，暂时无法定案",
    )


def _deduplicate_candidates(candidate_values: list[Any]) -> list[Any]:
    deduplicated: list[Any] = []
    for candidate in candidate_values:
        if candidate not in deduplicated:
            deduplicated.append(candidate)
    return deduplicated
