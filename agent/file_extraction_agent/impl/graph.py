"""file_extraction_agent 的内部 graph 编排层。"""

from __future__ import annotations

from typing import Any

from file_extraction_agent.impl.broad_extraction import run_broad_extraction
from file_extraction_agent.impl.resolution import run_resolution
from file_extraction_agent.impl.schemas import ExtractionInput, FieldDecision, FieldEvidence
from file_extraction_agent.impl.state import build_graph_state
from file_extraction_agent.impl.state import GraphState
from file_extraction_agent.schemas import (
    ExtractionContent,
    ExtractionResult,
    ExtractionTrace,
    FieldDefinition,
    TraceAction,
)


def run_extraction_graph(
    *,
    extraction_input: ExtractionInput,
    extractor_client: Any,
) -> ExtractionResult:
    """串联 broad extraction 与 resolution 两个内部节点。"""

    state = build_graph_state(extraction_input)
    try:
        state = run_broad_extraction(state=state, extractor_client=extractor_client)
    except Exception as exc:
        return _build_failed_result(
            state=state,
            failure_stage="broad_extraction",
            error=exc,
        )

    try:
        state = run_resolution(state=state, extractor_client=extractor_client)
    except Exception as exc:
        return _build_failed_result(
            state=state,
            failure_stage="resolution",
            error=exc,
        )

    if state.evidence_collection is None:
        return _build_failed_result(
            state=state,
            failure_stage="graph_mapping",
            error=ValueError("graph finished without evidence_collection"),
        )

    return _build_completed_result(state)


def _build_completed_result(state: GraphState) -> ExtractionResult:
    return ExtractionResult(
        status="completed",
        result=ExtractionContent(
            fields=[field_decision.to_field_result() for field_decision in state.field_decisions]
        ),
        trace=ExtractionTrace(
            fields=[field_decision.to_field_trace() for field_decision in state.field_decisions],
            warnings=state.warnings,
        ),
    )


def _build_failed_result(
    *,
    state: GraphState,
    failure_stage: str,
    error: Exception,
) -> ExtractionResult:
    failure_reason = _format_failure_reason(failure_stage=failure_stage, error=error)
    field_decisions = _field_decisions_with_failure_placeholders(
        state=state,
        failure_stage=failure_stage,
        error=error,
        failure_reason=failure_reason,
    )
    completed_field_names = [decision.field_name for decision in state.field_decisions]
    pending_field_names = [
        field.field_name
        for field in state.extraction_input.task_spec.fields
        if field.field_name not in set(completed_field_names)
    ]
    return ExtractionResult(
        status="failed",
        failure_reason=failure_reason,
        result=ExtractionContent(
            fields=[field_decision.to_field_result() for field_decision in field_decisions]
        ),
        trace=ExtractionTrace(
            fields=[field_decision.to_field_trace() for field_decision in field_decisions],
            warnings=[*state.warnings, failure_reason],
            metadata={
                "failure_stage": failure_stage,
                "error_type": type(error).__name__,
                "error_message": str(error),
                "completed_field_names": completed_field_names,
                "pending_field_names": pending_field_names,
            },
        ),
    )


def _field_decisions_with_failure_placeholders(
    *,
    state: GraphState,
    failure_stage: str,
    error: Exception,
    failure_reason: str,
) -> list[FieldDecision]:
    existing_by_field = {
        decision.field_name: decision
        for decision in state.field_decisions
    }
    decisions: list[FieldDecision] = []
    for field in state.extraction_input.task_spec.fields:
        existing_decision = existing_by_field.get(field.field_name)
        if existing_decision is not None:
            decisions.append(existing_decision)
            continue
        decisions.append(
            _build_failed_field_decision(
                state=state,
                field=field,
                failure_stage=failure_stage,
                error=error,
                failure_reason=failure_reason,
            )
        )
    return decisions


def _build_failed_field_decision(
    *,
    state: GraphState,
    field: FieldDefinition,
    failure_stage: str,
    error: Exception,
    failure_reason: str,
) -> FieldDecision:
    return FieldDecision(
        field_name=field.field_name,
        status="failed",
        evidence=_failure_evidence_for_field(
            state=state,
            field_name=field.field_name,
            failure_stage=failure_stage,
        ),
        trace_actions=[
            TraceAction(
                action_type="model_call_error",
                message=failure_reason,
                metadata={
                    "failure_stage": failure_stage,
                    "error_type": type(error).__name__,
                    "error_message": str(error),
                },
            )
        ],
        failure_reason=failure_reason,
    )


def _failure_evidence_for_field(
    *,
    state: GraphState,
    field_name: str,
    failure_stage: str,
) -> FieldEvidence:
    if state.evidence_collection is not None:
        evidence = next(
            (
                item
                for item in state.evidence_collection.fields
                if item.field_name == field_name
            ),
            None,
        )
        if evidence is not None:
            return FieldEvidence(
                field_name=evidence.field_name,
                relevant_block_ids=list(evidence.relevant_block_ids),
                evidence_texts=list(evidence.evidence_texts),
                evidence_refs=list(evidence.evidence_refs),
                local_status=evidence.local_status,
                local_notes=[
                    *list(evidence.local_notes),
                    f"{failure_stage} 失败，沿用失败前已有 broad evidence",
                ],
            )

    return FieldEvidence(
        field_name=field_name,
        local_status=f"{failure_stage}_failed",
        local_notes=[f"{failure_stage} 失败前没有可沿用 evidence"],
    )


def _format_failure_reason(*, failure_stage: str, error: Exception) -> str:
    return f"{failure_stage} 执行失败: {type(error).__name__}: {error}"
