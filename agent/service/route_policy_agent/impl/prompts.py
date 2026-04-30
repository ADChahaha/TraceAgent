"""route policy 小 LLM 的 prompt 组装层。"""

from __future__ import annotations

import json
from typing import Any

from service.route_policy_agent.impl.mapper import FieldPolicyContext
from service.route_policy_agent.schemas import PolicyOptions


def build_route_policy_messages(
    *,
    context: FieldPolicyContext,
    policy_options: PolicyOptions,
) -> list[dict[str, str]]:
    """为单字段 route 判断构造字段证据和抽取过程摘要 messages。"""

    return [
        {
            "role": "system",
            "content": (
                "你是字段 route policy 的第三方评价者。"
                "根据任务字段定义、字段输出、refs_with_text 中的证据文本，"
                "以及 field_process 中的 broad/resolution 过程摘要判断 route。"
                "如果 payload 包含 related_field_processes，它表示当前字段的来源字段"
                "在前面 broad/resolution 阶段查过什么、写入过多少候选、是否最终定案；"
                "派生数量字段或复制候选字段必须结合这些来源字段过程判断抽取路径是否充分。"
                "refs_with_text 是判断字段值是否被原文支持的唯一证据文本来源；"
                "field_process 和 related_field_processes 只用于判断 agent 是否用合理 search 查询词查过、"
                "是否写入候选、是否使用 count_field_candidates、是否执行 final_decision。"
                "route 只能是 accept、review 或 reject。"
                "不要重新抽取字段，不要输出新字段值；"
                "如果认为字段值需要修改，只能返回 review 并说明原因。"
                "如果 refs 文本不足以支持字段值，返回 review 或 reject。"
                "如果字段值有证据但搜索路径明显不足，也返回 review 并说明要人工检查。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "field_definition": context.field_definition.model_dump(),
                    "field_output": context.field_output.model_dump(),
                    "refs_with_text": _serialize_refs(
                        context=context,
                        policy_options=policy_options,
                    ),
                    "field_process": context.field_process.model_dump(),
                    "related_field_processes": [
                        process.model_dump()
                        for process in context.related_field_processes
                    ],
                    "allowed_routes": ["accept", "review", "reject"],
                },
                ensure_ascii=False,
            ),
        },
    ]


def _serialize_refs(
    *,
    context: FieldPolicyContext,
    policy_options: PolicyOptions,
) -> list[dict[str, Any]]:
    refs = context.refs_with_text[: policy_options.max_refs_per_field]
    return [
        {
            "document_id": ref.document_id,
            "page": ref.page,
            "block_id": ref.block_id,
            "span": ref.span,
            "text": _truncate_text(
                ref.text,
                max_chars=policy_options.max_ref_text_chars,
            ),
        }
        for ref in refs
    ]


def _truncate_text(text: str, *, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars]
