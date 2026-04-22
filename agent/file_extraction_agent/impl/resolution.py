"""file_extraction_agent 的 field resolution 节点。

当前实现先做一个最小 deterministic 版本，让 schema 与 graph 先完成结构重构：

```text
GraphState(graph_input=..., broad_output=...)
  -> 按 task_spec.fields 保持字段输出顺序
  -> 从 broad_output.fields 建 field_name -> evidence bundle 索引
  -> 有 evidence_texts 的字段先用第一条 evidence_text 作为占位 final_value
  -> 缺少 evidence bundle 或 evidence_texts 的字段输出 failed
  -> 同时写回 result_fields 与 trace_fields
```

后续真正接入 resolution agent 时，应替换这里的定案逻辑，但继续保持：

- `result_fields` 只放纯业务结果
- `trace_fields` 保存 broad / cross / lookup / reason
"""

from __future__ import annotations

from file_extraction_agent.impl.state import GraphState
from file_extraction_agent.schemas import (
    BroadExtractionOutput,
    FieldEvidenceBundle,
    FieldTraceRecord,
    ResolvedFieldResult,
    TaskSpec,
)


def run_resolution(*, state: GraphState) -> GraphState:
    """执行第二阶段字段定案，并把 result 与 trace 写回图状态。"""

    if state.broad_output is None:
        raise ValueError("resolution requires broad_output before resolving fields")

    state.result_fields, state.trace_fields = resolve_fields(
        task_spec=state.graph_input.task_spec,
        broad_output=state.broad_output,
    )
    return state


def resolve_fields(
    *,
    task_spec: TaskSpec,
    broad_output: BroadExtractionOutput,
) -> tuple[list[ResolvedFieldResult], list[FieldTraceRecord]]:
    """按 task spec 顺序把 broad evidence bundles 收口成 result + trace。"""

    broad_output_by_field = {
        field_output.field_name: field_output for field_output in broad_output.fields
    }
    result_fields: list[ResolvedFieldResult] = []
    trace_fields: list[FieldTraceRecord] = []

    for field in task_spec.fields:
        result_field, trace_field = resolve_single_field(
            field_name=field.field_name,
            field_output=broad_output_by_field.get(field.field_name),
        )
        result_fields.append(result_field)
        trace_fields.append(trace_field)

    return result_fields, trace_fields


def resolve_single_field(
    *,
    field_name: str,
    field_output: FieldEvidenceBundle | None,
) -> tuple[ResolvedFieldResult, FieldTraceRecord]:
    """把单字段 evidence bundle 收口成纯结果与字段 trace。"""

    if field_output is None or not field_output.evidence_texts:
        result_field = ResolvedFieldResult(
            field_name=field_name,
            status="failed",
        )
        trace_field = FieldTraceRecord(
            field_name=field_name,
            status="failed",
            broad_trace=(
                field_output.to_broad_trace()
                if field_output is not None
                else _missing_broad_trace()
            ),
            used_field_outputs=[field_name] if field_output is not None else [],
            extra_lookup_used=False,
            failure_reason="未找到可用证据",
        )
        return result_field, trace_field

    result_field = ResolvedFieldResult(
        field_name=field_name,
        status="resolved",
        final_value=field_output.evidence_texts[0],
    )
    trace_field = FieldTraceRecord(
        field_name=field_name,
        status="resolved",
        broad_trace=field_output.to_broad_trace(),
        used_field_outputs=[field_name],
        extra_lookup_used=False,
        reason="当前最小实现使用第一条 evidence_text 作为占位定案结果",
    )
    return result_field, trace_field


def _missing_broad_trace():
    return FieldEvidenceBundle(
        field_name="__missing__",
        local_status="missing",
    ).to_broad_trace()
