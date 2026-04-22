"""file_extraction_agent 的内部 prompt 组装层。

实现步骤：

```text
GraphInput / BroadExtractionOutput / target_field_name
  -> 先把 blocks、fields、run_config、metadata 收敛成稳定的可序列化摘要
  -> broad extraction 阶段输出面向 FieldEvidenceBundle 的系统指令
  -> field resolution 阶段先从 task_spec 找到目标字段定义，再从 broad_output 找到对应 evidence bundle
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
                "你负责基于标准化文档内容输出字段级 evidence bundle。"
                "返回值必须严格符合 BroadExtractionOutput；"
                "每个字段只做相关 blocks 和证据预选，不输出最终字段值；"
                "每个字段都要给出 relevant_block_ids、evidence_texts、"
                "evidence_refs、local_status、local_notes。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task_name": graph_input.task_spec.task_name,
                    "fields": _serialize_task_fields(graph_input),
                    "blocks": _serialize_blocks(graph_input),
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
                "返回值必须严格符合 result + trace 的字段级结构；"
                "只能输出 resolved 或 failed，并解释定案或失败原因。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
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
                            "relevant_block_ids": (
                                target_output.relevant_block_ids if target_output else []
                            ),
                            "evidence_texts": (
                                target_output.evidence_texts if target_output else []
                            ),
                            "local_status": (
                                target_output.local_status if target_output else "missing"
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
                    "blocks": _serialize_blocks(graph_input),
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


def _serialize_blocks(graph_input: GraphInput) -> list[dict[str, Any]]:
    return [block.model_dump() for block in graph_input.blocks]
