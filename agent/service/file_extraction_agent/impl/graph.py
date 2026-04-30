"""service.file_extraction_agent 的内部 graph 编排层。"""

from __future__ import annotations

from typing import Any

from service.file_extraction_agent.impl.broad.runner import run_broad_stage
from service.file_extraction_agent.impl.resolution.runner import run_resolution_stage
from service.file_extraction_agent.impl.schemas import (
    Candidate,
    ExtractionInput,
    FieldDecision,
)
from service.file_extraction_agent.impl.state import GraphState, IndexedSource, build_graph_state
from service.file_extraction_agent.schemas import (
    EvidenceSummary,
    ExtractionContent,
    ExtractionResult,
    ExtractionTrace,
    FieldEvidenceRef,
    FieldResult,
    FieldTrace,
    TraceAction,
)


def run_extraction_graph(
    *,
    extraction_input: ExtractionInput,
    extractor_client: Any | None = None,
    broad_extractor_client: Any | None = None,
    resolution_extractor_client: Any | None = None,
) -> ExtractionResult:
    """串联 broad 和 resolution 两个内部阶段。"""

    broad_client = broad_extractor_client or extractor_client
    resolution_client = resolution_extractor_client or extractor_client
    if broad_client is None or resolution_client is None:
        raise ValueError("extractor_client or both stage clients is required")

    state = build_graph_state(extraction_input)
    try:
        state = run_broad_stage(state=state, extractor_client=broad_client)
    except Exception as exc:
        return build_failed_result(
            state=state,
            failure_stage="broad",
            error=exc,
        )

    try:
        state = run_resolution_stage(state=state, extractor_client=resolution_client)
    except Exception as exc:
        return build_failed_result(
            state=state,
            failure_stage="resolution",
            error=exc,
        )

    return map_state_to_result(state)


def map_state_to_result(state: GraphState) -> ExtractionResult:
    """把内部状态映射成外部稳定 `ExtractionResult`。"""

    field_results: list[FieldResult] = []
    field_traces: list[FieldTrace] = []
    for field in state.extraction_input.task_spec.fields:
        decision = state.field_decisions.get(field.field_name)
        if decision is None:
            decision = FieldDecision(
                field_name=field.field_name,
                status="failed",
                failure_reason="resolution did not produce field decision",
            )
        field_results.append(_field_result_from_decision(decision))
        field_traces.append(_field_trace_from_decision(state=state, decision=decision))

    return ExtractionResult(
        status="completed",
        result=ExtractionContent(fields=field_results),
        trace=ExtractionTrace(fields=field_traces, warnings=list(state.warnings)),
    )


def build_failed_result(
    *,
    state: GraphState,
    failure_stage: str,
    error: Exception,
) -> ExtractionResult:
    """把中途失败收口成可追踪的失败结果。"""

    failure_reason = _format_failure_reason(failure_stage=failure_stage, error=error)
    completed_field_names = _completed_field_names_for_failure(
        state=state,
        failure_stage=failure_stage,
    )
    pending_field_names = _pending_field_names(
        state=state,
        completed_field_names=completed_field_names,
    )
    failure_action_field_name = pending_field_names[0] if pending_field_names else None

    field_results: list[FieldResult] = []
    field_traces: list[FieldTrace] = []
    for field in state.extraction_input.task_spec.fields:
        decision = state.field_decisions.get(field.field_name)
        if decision is None:
            decision = FieldDecision(
                field_name=field.field_name,
                status="failed",
                failure_reason=failure_reason,
            )
            extra_actions = _failure_extra_actions(
                field_name=field.field_name,
                failure_action_field_name=failure_action_field_name,
                failure_stage=failure_stage,
                failure_reason=failure_reason,
                error=error,
            )
        else:
            extra_actions = []
        field_results.append(_field_result_from_decision(decision))
        field_traces.append(
            _field_trace_from_decision(
                state=state,
                decision=decision,
                extra_actions=extra_actions,
            )
        )

    return ExtractionResult(
        status="failed",
        failure_reason=failure_reason,
        result=ExtractionContent(fields=field_results),
        trace=ExtractionTrace(
            fields=field_traces,
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


def _completed_field_names_for_failure(
    *,
    state: GraphState,
    failure_stage: str,
) -> list[str]:
    if failure_stage == "broad":
        return list(state.broad_finishes)
    return list(state.field_decisions)


def _pending_field_names(
    *,
    state: GraphState,
    completed_field_names: list[str],
) -> list[str]:
    completed = set(completed_field_names)
    return [
        field.field_name
        for field in state.extraction_input.task_spec.fields
        if field.field_name not in completed
    ]


def _failure_extra_actions(
    *,
    field_name: str,
    failure_action_field_name: str | None,
    failure_stage: str,
    failure_reason: str,
    error: Exception,
) -> list[TraceAction]:
    if field_name != failure_action_field_name:
        return []
    return [
        TraceAction(
            action_type="model_call_error",
            message=failure_reason,
            metadata={
                "failure_stage": failure_stage,
                "error_type": type(error).__name__,
                "error_message": str(error),
            },
        )
    ]


def _field_result_from_decision(decision: FieldDecision) -> FieldResult:
    return FieldResult(
        field_name=decision.field_name,
        status=decision.status,
        value=decision.value,
    )


def _field_trace_from_decision(
    *,
    state: GraphState,
    decision: FieldDecision,
    extra_actions: list[TraceAction] | None = None,
) -> FieldTrace:
    return FieldTrace(
        field_name=decision.field_name,
        status=decision.status,
        evidence=_evidence_summary_for_decision(state=state, decision=decision),
        related_fields=list(decision.related_fields),
        actions=[
            *[
                _trace_action_from_record(
                    state=state,
                    decision=decision,
                    record=record,
                )
                for record in state.actions.get(decision.field_name, [])
            ],
            *(extra_actions or []),
        ],
        reason=decision.reason,
        failure_reason=decision.failure_reason,
    )


def _evidence_summary_for_decision(
    *,
    state: GraphState,
    decision: FieldDecision,
) -> EvidenceSummary:
    candidates = _candidates_for_decision(state=state, decision=decision)
    refs = [_external_ref_for_candidate(state=state, candidate=candidate) for candidate in candidates]
    return EvidenceSummary(
        block_ids=_deduplicate_preserving_order(
            [ref.block_id for ref in refs if ref.block_id]
        ),
        texts=[candidate.text for candidate in candidates],
        refs=refs,
        status="candidate_resolved" if decision.status == "resolved" else "candidate_failed",
        notes=[
            f"field decision referenced candidate_ids: {', '.join(decision.candidate_ids)}"
            if decision.candidate_ids
            else "field decision did not reference candidates",
        ],
    )


def _trace_action_from_record(
    *,
    state: GraphState,
    decision: FieldDecision,
    record,
) -> TraceAction:
    candidate_ids = set(record.candidate_ids)
    final_candidate_ids = set(decision.candidate_ids)
    return TraceAction(
        action_type=record.action_type,
        message=record.message,
        refs=[
            _external_ref_for_source(source)
            for source in _sources_for_refs(state=state, refs=record.refs)
        ],
        used_in_final_decision=bool(candidate_ids & final_candidate_ids)
        or record.action_type == "final_decision",
        metadata={
            **record.metadata,
            "stage": record.stage,
            "candidate_ids": list(record.candidate_ids),
            "refs": list(record.refs),
        },
    )


def _candidates_for_decision(
    *,
    state: GraphState,
    decision: FieldDecision,
) -> list[Candidate]:
    candidates_by_id = {
        candidate.candidate_id: candidate
        for candidate in state.candidates.get(decision.field_name, [])
    }
    return [
        candidates_by_id[candidate_id]
        for candidate_id in decision.candidate_ids
        if candidate_id in candidates_by_id
    ]


def _external_ref_for_candidate(
    *,
    state: GraphState,
    candidate: Candidate,
) -> FieldEvidenceRef:
    source = state.paragraph_index.get(candidate.ref) or state.table_row_index.get(candidate.ref)
    if source is None:
        return FieldEvidenceRef(
            document_id="",
            block_id=None,
            span=candidate.ref,
        )
    return _external_ref_for_source(source)


def _sources_for_refs(*, state: GraphState, refs: list[str]) -> list[IndexedSource]:
    sources: list[IndexedSource] = []
    for ref in refs:
        source = state.paragraph_index.get(ref) or state.table_row_index.get(ref)
        if source is not None:
            sources.append(source)
    return sources


def _external_ref_for_source(source: IndexedSource) -> FieldEvidenceRef:
    return FieldEvidenceRef(
        document_id=source.document_id,
        page=source.page_no,
        block_id=source.block_id,
        span=source.locator,
    )


def _deduplicate_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduplicated: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduplicated.append(value)
    return deduplicated


def _format_failure_reason(*, failure_stage: str, error: Exception) -> str:
    return f"{failure_stage} 执行失败: {type(error).__name__}: {error}"
