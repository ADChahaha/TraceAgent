"""route policy 小 LLM 的 prompt 组装层。"""

from __future__ import annotations

import json
from typing import Any

from service.route_policy_agent.impl.mapper import FieldPolicyContext


def build_route_policy_messages(
    *,
    context: FieldPolicyContext,
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
                "如果 field_process.diagnostics 里有 query_audit 或 table_audit，"
                "它们只是工具观察到的查表事实，例如返回行数、筛选列空白数量、非空分布和输出列空值。"
                "不要因为筛选列有空白就自动 review；要结合 field_resolution.reason 判断模型是否合理解释了这些观察。"
                "如果存在近似未选中行、选中输出为空、结构错位等事实，且模型没有解释或证据无法支持字段值，返回 review。"
                "route 只能是 accept、review 或 reject。"
                "不要重新抽取字段，不要输出新字段值；"
                "如果认为字段值需要修改，只能返回 review 并说明原因。"
                "如果 refs 文本不足以支持字段值，返回 review 或 reject。"
                "如果字段值有证据但搜索路径明显不足，也返回 review 并说明要人工检查。"
                "Few-shot examples for query_audit:"
                "例 1：字段要求抽取某个目标类别下的名称。query_audit.summary 显示 WHERE 的类别列有空白。"
                "如果 refs_with_text、相邻列、表注或表头、分组标题能明确证明这些空白行属于非目标类别，"
                "并且选中行的输出列完整，判断：accept。原因：空白筛选列必须结合表格上下文判断，"
                "此处上下文证明空白行不属于目标类别。"
                "例 2：字段要求抽取某个目标类别下的名称。query_audit.summary 显示 WHERE 的类别列有空白、"
                "near_match_rows 或输出列空值。field_resolution.reason 只说'空白值未被选中属正常'，"
                "但没有引用表头、表注、分组标题或相邻列证明这些空白行是非目标类别。判断：review。"
                "原因：不能只因为空白行未被 WHERE 选中就说正常；如果空白行可能仍是有效数据，"
                "需要人工检查或重新查询。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "field_definition": context.field_definition.model_dump(exclude_none=True),
                    "field_output": context.field_output.model_dump(exclude_none=True),
                    "refs_with_text": _serialize_refs(context=context),
                    "field_process": context.field_process.model_dump(exclude_none=True),
                    "related_field_processes": [
                        process.model_dump(exclude_none=True)
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
) -> list[dict[str, Any]]:
    return [
        {
            "document_id": ref.document_id,
            "page": ref.page,
            "block_id": ref.block_id,
            "span": ref.span,
            "text": ref.text,
        }
        for ref in context.refs_with_text
    ]
