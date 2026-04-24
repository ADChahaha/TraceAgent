"""file_extraction_agent 的内部 prompt 组装层。"""

from __future__ import annotations

import json
from typing import Any

from file_extraction_agent.impl.schemas import EvidenceCollection, ExtractionInput


def build_broad_extraction_messages(extraction_input: ExtractionInput) -> list[dict[str, str]]:
    """为 broad extraction 阶段构造 messages。"""

    return [
        {
            "role": "system",
            "content": (
                "你负责基于标准化文档内容输出字段级 evidence。"
                "返回值必须严格符合 EvidenceCollection；"
                "每个字段只做相关 blocks 和证据预选，不输出最终字段值；"
                "如果字段带 validation_rules，必须按其中的 filter/exclude/target_column "
                "筛选证据，evidence_texts 只能放满足规则的最小证据片段；"
                "每个字段都要给出 relevant_block_ids、evidence_texts、"
                "evidence_refs、local_status、local_notes。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task_name": extraction_input.task_spec.task_name,
                    "fields": _serialize_task_fields(extraction_input),
                    "blocks": _serialize_blocks(extraction_input),
                    "options": extraction_input.options.model_dump(),
                    "metadata": extraction_input.metadata,
                },
                ensure_ascii=False,
            ),
        },
    ]


def build_field_resolution_messages(
    *,
    extraction_input: ExtractionInput,
    target_field_name: str,
    evidence_collection: EvidenceCollection,
    tool_evidence: list[dict[str, Any]] | None = None,
    tool_records: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    """为 field resolution 阶段构造 messages。"""

    target_field = next(
        (
            field
            for field in extraction_input.task_spec.fields
            if field.field_name == target_field_name
        ),
        None,
    )
    target_evidence = next(
        (
            field_evidence
            for field_evidence in evidence_collection.fields
            if field_evidence.field_name == target_field_name
        ),
        None,
    )

    return [
        {
            "role": "system",
            "content": (
                "你负责对单个目标字段做 field resolution。"
                "必须返回 FieldResolutionAction。"
                "如果当前 broad evidence 足够，返回 action=final_decision 和轻量 decision；"
                "decision 只填写 status、value、used_block_ids、related_fields、reason 或 failure_reason；"
                "value 只能是字符串、数字、布尔值、字符串列表或 null，不能返回对象；"
                "不要在 decision 中构造 evidence、refs、lookup_records 或 trace_actions；"
                "used_block_ids 必须来自已提供 evidence 或 tool_evidence 中的 block id；"
                "如果 broad 给出的 blocks 不够完整，先返回 lookup_blocks 并说明 query_reason；"
                "如果需要参考其他字段 evidence，先返回 get_field_bundle；"
                "工具返回后仍然必须由你返回 final_decision。"
                "最终 FieldDecision 只能是 resolved 或 failed，并解释定案或失败原因。"
                "如果 target_field 带 validation_rules，最终值必须满足这些规则；"
                "不要把 exclude 条件命中的证据混入最终值。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task_name": extraction_input.task_spec.task_name,
                    "target_field_name": target_field_name,
                    "target_field": (
                        {
                            "field_name": target_field.field_name,
                            "display_name": target_field.display_name,
                            "type": target_field.type,
                            "required": target_field.required,
                            "critical": target_field.critical,
                            "allow_missing": target_field.allow_missing,
                            "validation_rules": target_field.validation_rules,
                            "cross_field_hints": target_field.cross_field_hints,
                            "lookup_hints": target_field.lookup_hints,
                            "enum_values": target_field.enum_values,
                            "relevant_block_ids": (
                                target_evidence.relevant_block_ids if target_evidence else []
                            ),
                            "evidence_texts": (
                                target_evidence.evidence_texts if target_evidence else []
                            ),
                            "local_status": (
                                target_evidence.local_status if target_evidence else "missing"
                            ),
                            "local_notes": (
                                target_evidence.local_notes if target_evidence else []
                            ),
                        }
                        if target_field is not None
                        else None
                    ),
                    "all_field_evidence": [
                        field_evidence.model_dump()
                        for field_evidence in evidence_collection.fields
                    ],
                    "tool_evidence": tool_evidence or [],
                    "tool_records": tool_records or [],
                },
                ensure_ascii=False,
            ),
        },
    ]


def _serialize_task_fields(extraction_input: ExtractionInput) -> list[dict[str, Any]]:
    return [
        {
            "field_name": field.field_name,
            "display_name": field.display_name,
            "type": field.type,
            "required": field.required,
            "critical": field.critical,
            "allow_missing": field.allow_missing,
            "validation_rules": field.validation_rules,
            "cross_field_hints": field.cross_field_hints,
            "lookup_hints": field.lookup_hints,
            "enum_values": field.enum_values,
        }
        for field in extraction_input.task_spec.fields
    ]


def _serialize_blocks(extraction_input: ExtractionInput) -> list[dict[str, Any]]:
    return [block.model_dump() for block in extraction_input.blocks]
