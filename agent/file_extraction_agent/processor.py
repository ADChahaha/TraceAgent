"""file_extraction_agent 对外统一入口。

实现步骤：

```text
调用方传入 session_id + documents，再传 task_spec 或 task_spec_name
  -> extract(...) 先把外部 session 输入交给 input_adapter.build_graph_input(...)
  -> input_adapter 负责选择 task_spec：显式传入就直接用；否则按 task_spec_name 从 task_specs/*.json 加载
  -> input_adapter 再用 session_id / documents / task_spec / run_config / metadata 组装 GraphInput
  -> 如果没传 extractor_client，就调用 build_extractor_client_from_env() 构造默认客户端
  -> 把 GraphInput 压成给 broad extraction 使用的 messages
  -> 调用 extractor_client.invoke(..., output_schema=BroadExtractionOutput)
  -> 按 task_spec.fields 顺序收口 broad output：单一候选值 resolved，没有候选值 failed，多候选冲突也 failed
  -> 返回 ExtractionResult(broad_output, resolved_fields, run_trace)
```
"""

from __future__ import annotations

from typing import Any

from file_extraction_agent.extractor_client import build_extractor_client_from_env
from file_extraction_agent import input_adapter
from file_extraction_agent.impl.prompts import build_broad_extraction_messages
from file_extraction_agent.input_adapter import build_graph_input
from file_extraction_agent.schemas import (
    BroadExtractionFieldOutput,
    BroadExtractionOutput,
    ExtractionResult,
    NormalizedDocument,
    ResolvedFieldOutput,
    RunConfig,
    RunTrace,
    TaskSpec,
)


TASK_SPECS_DIR = input_adapter.TASK_SPECS_DIR
TaskSpecNotFoundError = input_adapter.TaskSpecNotFoundError


def extract(
    *,
    session_id: str,
    documents: list[NormalizedDocument],
    task_spec: TaskSpec | None = None,
    task_spec_name: str | None = None,
    run_config: RunConfig | None = None,
    metadata: dict[str, Any] | None = None,
    extractor_client: Any | None = None,
) -> ExtractionResult:
    """消费外部已校验好的输入，执行最小可用的字段抽取收口流程。"""

    input_adapter.TASK_SPECS_DIR = TASK_SPECS_DIR
    graph_input = build_graph_input(
        session_id=session_id,
        documents=documents,
        task_spec=task_spec,
        task_spec_name=task_spec_name,
        run_config=run_config,
        metadata=metadata,
    )
    client = (
        extractor_client
        if extractor_client is not None
        else build_extractor_client_from_env()
    )
    broad_output = client.invoke(
        output_schema=BroadExtractionOutput,
        messages=build_broad_extraction_messages(graph_input),
    )
    resolved_fields = _resolve_fields(
        task_spec=graph_input.task_spec,
        broad_output=broad_output,
    )
    return ExtractionResult(
        broad_output=broad_output,
        resolved_fields=resolved_fields,
        run_trace=RunTrace(rounds=1),
    )


def _resolve_fields(
    *,
    task_spec: TaskSpec,
    broad_output: BroadExtractionOutput,
) -> list[ResolvedFieldOutput]:
    broad_output_by_field = {
        field_output.field_name: field_output for field_output in broad_output.fields
    }
    resolved_fields: list[ResolvedFieldOutput] = []
    for field in task_spec.fields:
        field_output = broad_output_by_field.get(field.field_name)
        resolved_fields.append(
            _resolve_single_field(
                field_name=field.field_name,
                field_output=field_output,
            )
        )
    return resolved_fields


def _resolve_single_field(
    *,
    field_name: str,
    field_output: BroadExtractionFieldOutput | None,
) -> ResolvedFieldOutput:
    if field_output is None or not field_output.candidate_values:
        return ResolvedFieldOutput(
            field_name=field_name,
            status="failed",
            used_field_outputs=[field_name] if field_output is not None else [],
            extra_lookup_used=False,
            failure_reason="未找到可用候选值",
        )

    normalized_candidates: list[Any] = []
    for candidate in field_output.candidate_values:
        if candidate not in normalized_candidates:
            normalized_candidates.append(candidate)

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
