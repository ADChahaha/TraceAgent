"""file_extraction_agent 的内部 prompt 组装层。

实现步骤：

```text
GraphInput / BroadExtractionOutput / target_field_name
  -> 先把 documents、fields、run_config、metadata 收敛成稳定的可序列化摘要
  -> broad extraction 阶段输出面向 BroadExtractionOutput 的系统指令
  -> field resolution 阶段先从 task_spec 找到目标字段定义，再从 broad_output 找到对应候选 bundle
  -> 再把全局字段输出一并压成 JSON payload
  -> 返回 extractor client 可直接消费的 messages 列表
```
"""

from __future__ import annotations

import json
from typing import Any

from file_extraction_agent.schemas import (
    BroadExtractionOutput,
    GraphInput,
)


def build_broad_extraction_messages(graph_input: GraphInput) -> list[dict[str, str]]:
    """为 broad extraction 阶段构造 messages。"""

    return [
        {
            "role": "system",
            "content": (
                "你负责基于标准化文档内容输出字段级 broad extraction 结果。"
                "返回值必须严格符合 BroadExtractionOutput；"
                "每个字段都要给出 candidate_values、evidence_texts、"
                "evidence_refs、local_status、local_validation、local_notes。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "session_id": graph_input.session_id,
                    "task_name": graph_input.task_spec.task_name,
                    "fields": _serialize_task_fields(graph_input),
                    "documents": _serialize_documents(graph_input),
                    "run_config": graph_input.run_config.model_dump(),
                    "metadata": graph_input.metadata,
                },
                ensure_ascii=False,
            ),
        },
    ]


def build_field_resolution_messages(
    *,
    graph_input: GraphInput,
    target_field_name: str,
    broad_output: BroadExtractionOutput,
) -> list[dict[str, str]]:
    """为 field resolution 阶段构造 messages。"""

    target_field = next(
        (
            field
            for field in graph_input.task_spec.fields
            if field.field_name == target_field_name
        ),
        None,
    )
    target_output = next(
        (
            field_output
            for field_output in broad_output.fields
            if field_output.field_name == target_field_name
        ),
        None,
    )

    return [
        {
            "role": "system",
            "content": (
                "你负责对单个目标字段做 field resolution。"
                "返回值必须严格符合 ResolvedFieldOutput；"
                "只能输出 resolved 或 failed，并解释定案或失败原因。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "session_id": graph_input.session_id,
                    "task_name": graph_input.task_spec.task_name,
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
                            "candidate_values": (
                                target_output.candidate_values if target_output else []
                            ),
                            "evidence_texts": (
                                target_output.evidence_texts if target_output else []
                            ),
                            "local_status": (
                                target_output.local_status if target_output else "missing"
                            ),
                            "local_validation": (
                                target_output.local_validation if target_output else {}
                            ),
                            "local_notes": (
                                target_output.local_notes if target_output else []
                            ),
                        }
                        if target_field is not None
                        else None
                    ),
                    "all_field_outputs": [
                        field_output.model_dump() for field_output in broad_output.fields
                    ],
                    "documents": _serialize_documents(graph_input),
                },
                ensure_ascii=False,
            ),
        },
    ]


def _serialize_task_fields(graph_input: GraphInput) -> list[dict[str, Any]]:
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
        for field in graph_input.task_spec.fields
    ]


def _serialize_documents(graph_input: GraphInput) -> list[dict[str, Any]]:
    return [
        {
            "document_id": document.document_id,
            "markdown": document.markdown,
            "md_list": document.md_list,
            "blocks": [block.model_dump() for block in document.blocks],
            "metadata": document.metadata,
        }
        for document in graph_input.documents
    ]
