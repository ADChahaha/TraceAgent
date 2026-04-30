"""候选证据池读写工具。"""

from __future__ import annotations

from service.file_extraction_agent.impl.schemas import Candidate, ToolActionRecord
from service.file_extraction_agent.impl.state import GraphState, record_action


def add_broad_candidate(
    *,
    state: GraphState,
    field_name: str,
    refs: list[str],
    reason: str,
) -> list[Candidate]:
    """broad 阶段把搜索 ref 写入字段候选池。"""

    candidates = _add_candidates(
        state=state,
        field_name=field_name,
        refs=refs,
        reason=reason,
        source_stage="broad",
    )
    record_action(
        state,
        field_name=field_name,
        action=ToolActionRecord(
            field_name=field_name,
            stage="broad",
            action_type="add_broad_candidate",
            message=reason,
            refs=refs,
            candidate_ids=[candidate.candidate_id for candidate in candidates],
        ),
    )
    return candidates


def add_resolution_candidate(
    *,
    state: GraphState,
    field_name: str,
    refs: list[str],
    reason: str,
) -> list[Candidate]:
    """resolution 阶段把二次搜索 ref 写入同一个字段候选池。"""

    candidates = _add_candidates(
        state=state,
        field_name=field_name,
        refs=refs,
        reason=reason,
        source_stage="resolution",
    )
    record_action(
        state,
        field_name=field_name,
        action=ToolActionRecord(
            field_name=field_name,
            stage="resolution",
            action_type="add_resolution_candidate",
            message=reason,
            refs=refs,
            candidate_ids=[candidate.candidate_id for candidate in candidates],
        ),
    )
    return candidates


def get_candidate_bundle(*, state: GraphState, field_name: str) -> list[Candidate]:
    """按字段读取候选池，并记录本次读取动作。"""

    candidates = list(state.candidates.get(field_name, []))
    record_action(
        state,
        field_name=field_name,
        action=ToolActionRecord(
            field_name=field_name,
            stage="resolution",
            action_type="get_candidate_bundle",
            candidate_ids=[candidate.candidate_id for candidate in candidates],
        ),
    )
    return candidates


def _add_candidates(
    *,
    state: GraphState,
    field_name: str,
    refs: list[str],
    reason: str,
    source_stage: str,
) -> list[Candidate]:
    field_candidates = state.candidates.setdefault(field_name, [])
    returned: list[Candidate] = []
    for ref in refs:
        text = _text_for_ref(state=state, ref=ref)
        existing = next(
            (candidate for candidate in field_candidates if candidate.ref == ref),
            None,
        )
        if existing is not None:
            returned.append(existing)
            continue
        candidate = Candidate(
            candidate_id=f"c{len(field_candidates) + 1}",
            field_name=field_name,
            source_stage=source_stage,
            ref=ref,
            text=text,
            reason=reason,
        )
        field_candidates.append(candidate)
        returned.append(candidate)
    return returned


def _text_for_ref(*, state: GraphState, ref: str) -> str:
    source = state.paragraph_index.get(ref) or state.table_row_index.get(ref)
    if source is None:
        raise ValueError(f"unknown evidence ref: {ref}")
    return source.text
