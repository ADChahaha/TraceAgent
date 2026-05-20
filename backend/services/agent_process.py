from __future__ import annotations

from typing import Any

from backend.crud.json_utils import loads_json


_MISSING = object()

BlockLookup = dict[str, dict[str, Any]]


def serialize_field_agent_process(
    trace: dict[str, Any] | None,
    *,
    value: Any = _MISSING,
    block_lookup: BlockLookup | None = None,
) -> dict[str, Any] | None:
    if trace is None:
        return None
    return build_field_agent_process(
        field_name=trace["field_name"],
        status=trace["trace_status"],
        evidence=loads_json(trace["evidence_json"], {}),
        related_fields=loads_json(trace["related_fields_json"], []),
        actions=loads_json(trace["actions_json"], []),
        reason=trace["reason"],
        failure_reason=trace["failure_reason"],
        value=value,
        block_lookup=block_lookup,
    )


def build_field_agent_process(
    *,
    field_name: str | None,
    status: str | None,
    evidence: dict[str, Any],
    related_fields: list[str],
    actions: list[dict[str, Any]],
    reason: str | None,
    failure_reason: str | None,
    value: Any = _MISSING,
    block_lookup: BlockLookup | None = None,
) -> dict[str, Any]:
    enriched_evidence = enrich_evidence_blocks(evidence, block_lookup or {})
    process = {
        "field_name": field_name,
        "status": status,
        "evidence": enriched_evidence,
        "related_fields": related_fields,
        "actions": actions,
        "reason": reason,
        "failure_reason": failure_reason,
        "process_steps": build_field_process_steps(
            field_name=field_name,
            status=status,
            evidence=enriched_evidence,
            related_fields=related_fields,
            actions=actions,
            reason=reason,
            failure_reason=failure_reason,
            value=value,
        ),
    }
    if value is not _MISSING:
        process["value"] = value
    return process


def build_field_process_steps(
    *,
    field_name: str | None,
    status: str | None,
    evidence: dict[str, Any],
    related_fields: list[str],
    actions: list[dict[str, Any]],
    reason: str | None,
    failure_reason: str | None,
    value: Any = _MISSING,
) -> list[dict[str, Any]]:
    broad_actions, resolution_actions = _split_process_actions(actions)
    resolution_step: dict[str, Any] = {
        "stage": "field_resolution",
        "title": "第二步 resolution / tool",
        "status": "used" if resolution_actions or related_fields else "completed",
        "related_fields": related_fields,
        "actions": resolution_actions,
        "output_fields": _build_resolution_output_fields(
            field_name=field_name,
            status=status,
            value=value,
            reason=reason,
            failure_reason=failure_reason,
        ),
        "notes": _build_resolution_notes(
            related_fields=related_fields,
            actions=resolution_actions,
        ),
    }

    final_step: dict[str, Any] = {
        "stage": "final_result",
        "title": "第三步 agent result",
        "status": status,
        "reason": reason,
        "failure_reason": failure_reason,
    }
    if value is not _MISSING:
        final_step["value"] = value

    steps = [
        {
            "stage": "broad_extraction",
            "title": "第一步 broad extraction",
            "status": evidence.get("status") or status,
            "evidence": evidence,
            "actions": broad_actions,
        },
        resolution_step,
        final_step,
    ]
    return steps


def _split_process_actions(
    actions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    broad_actions: list[dict[str, Any]] = []
    resolution_actions: list[dict[str, Any]] = []
    for action in actions:
        if _action_belongs_to_broad(action):
            broad_actions.append(action)
        else:
            resolution_actions.append(action)
    return broad_actions, resolution_actions


def _action_belongs_to_broad(action: dict[str, Any]) -> bool:
    metadata = action.get("metadata") if isinstance(action.get("metadata"), dict) else {}
    stage = metadata.get("stage")
    if stage:
        return stage == "broad"
    return action.get("action_type") in {"search_grep", "add_broad_candidate", "finish_broad"}


def _build_resolution_output_fields(
    *,
    field_name: str | None,
    status: str | None,
    value: Any,
    reason: str | None,
    failure_reason: str | None,
) -> list[dict[str, Any]]:
    if not field_name:
        return []
    output: dict[str, Any] = {
        "field_name": field_name,
        "status": status,
    }
    if value is not _MISSING:
        output["value"] = value
    if reason:
        output["reason"] = reason
    if failure_reason:
        output["failure_reason"] = failure_reason
    return [output]


def _build_resolution_notes(
    *,
    related_fields: list[str],
    actions: list[dict[str, Any]],
) -> list[str]:
    notes: list[str] = []
    if related_fields:
        notes.append(f"读取相关字段：{', '.join(related_fields)}")

    for action in actions:
        action_type = action.get("action_type") or "action"
        message = action.get("message")
        used_suffix = "，参与最终定案" if action.get("used_in_final_decision") else ""
        if message:
            notes.append(f"执行 {action_type}：{message}{used_suffix}。")
        else:
            notes.append(f"执行 {action_type}{used_suffix}。")

    if not notes:
        notes.append("未记录额外 tool/action；resolution 直接将候选证据定案为字段输出。")

    return notes


def build_document_block_lookup(documents: list[dict[str, Any]]) -> BlockLookup:
    lookup: BlockLookup = {}
    for document in documents:
        for block in loads_json(document["blocks_json"], []):
            block_id = block.get("block_id")
            if not block_id:
                continue
            lookup[block_id] = _normalize_candidate_block(
                block,
                fallback_document_id=document["id"],
            )
    return lookup


def enrich_evidence_blocks(
    evidence: dict[str, Any],
    block_lookup: BlockLookup,
) -> dict[str, Any]:
    enriched = dict(evidence)
    blocks = _resolve_candidate_blocks(enriched, block_lookup)
    if blocks:
        enriched["blocks"] = blocks
    return enriched


def _resolve_candidate_blocks(
    evidence: dict[str, Any],
    block_lookup: BlockLookup,
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    seen: set[str] = set()

    for block in evidence.get("blocks") or []:
        normalized = _normalize_candidate_block(block)
        block_id = normalized.get("block_id")
        if block_id:
            seen.add(block_id)
        blocks.append(normalized)

    block_ids = [block_id for block_id in evidence.get("block_ids") or [] if block_id]
    refs = [ref for ref in evidence.get("refs") or [] if isinstance(ref, dict)]
    for ref in refs:
        block_id = ref.get("block_id")
        if block_id:
            block_ids.append(block_id)

    texts = evidence.get("texts") or []
    for index, block_id in enumerate(block_ids):
        if block_id in seen:
            continue
        source = block_lookup.get(block_id)
        if source is None and index < len(texts):
            source = {"block_id": block_id, "text": texts[index]}
        if source is None:
            continue
        normalized = _normalize_candidate_block(source)
        if not normalized.get("text"):
            continue
        blocks.append(normalized)
        seen.add(block_id)

    if blocks:
        return blocks

    return [
        _normalize_candidate_block({"text": text})
        for text in texts
        if isinstance(text, str) and text.strip()
    ]


def _normalize_candidate_block(
    block: dict[str, Any],
    *,
    fallback_document_id: str | None = None,
) -> dict[str, Any]:
    page = block.get("page") or block.get("page_no")
    normalized: dict[str, Any] = {
        "document_id": block.get("document_id") or fallback_document_id,
        "block_id": block.get("block_id"),
        "page": page,
        "text": block.get("text") or "",
        "kind": block.get("kind") or "text",
    }
    return {key: value for key, value in normalized.items() if value is not None}
