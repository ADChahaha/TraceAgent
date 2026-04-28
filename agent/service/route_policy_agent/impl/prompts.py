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
    """为单字段 route 判断构造只含字段定义、字段输出和 refs 文本的 messages。"""

    return [
        {
            "role": "system",
            "content": (
                "你是字段 route policy 的第三方评价者。"
                "只根据任务字段定义、字段输出和 refs_with_text 中的证据文本判断 route。"
                "route 只能是 accept、review 或 reject。"
                "不要重新抽取字段，不要输出新字段值；"
                "如果认为字段值需要修改，只能返回 review 并说明原因。"
                "如果 refs 文本不足以支持字段值，返回 review 或 reject。"
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
