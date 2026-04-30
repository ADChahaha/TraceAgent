"""resolution 阶段 prompt 组装。"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from service.file_extraction_agent.impl.state import GraphState


def build_resolution_messages(
    *,
    state: GraphState,
    tool_results: list[Any],
) -> list[dict[str, str]]:
    """构造共享 resolution loop 的模型输入。"""

    fields = list(state.extraction_input.task_spec.fields)
    pending_field_names = [
        field.field_name
        for field in fields
        if field.field_name not in state.field_decisions
    ]
    candidate_bundles = {
        field.field_name: _candidate_bundle_for_field(
            state=state,
            field_name=field.field_name,
        )
        for field in fields
    }
    total_candidate_count = sum(len(state.candidates.get(field.field_name, [])) for field in fields)
    included_candidate_count = sum(len(items) for items in candidate_bundles.values())
    payload = {
        "task_name": state.extraction_input.task_spec.task_name,
        "fields": [field.model_dump() for field in fields],
        "pending_fields": pending_field_names,
        "tool_contract": _resolution_tool_contract(),
        "candidate_bundles_by_field": candidate_bundles,
        "completed_fields": [
            {
                "field_name": decision.field_name,
                "status": decision.status,
                "value": decision.value,
            }
            for decision in state.field_decisions.values()
        ],
        "prompt_budget": {
            "total_candidate_count": total_candidate_count,
            "included_candidate_count": included_candidate_count,
            "omitted_candidate_count": max(0, total_candidate_count - included_candidate_count),
            "max_resolution_candidates": state.extraction_input.options.max_resolution_candidates,
        },
    }
    messages = [
        {
            "role": "system",
            "content": (
                "你是 field resolution 阶段，负责为所有待处理字段输出最终定案。"
                "必须返回 FieldResolutionAction。"
                "工具语义必须以 user payload 里的 tool_contract 为准，不能只按函数名猜。"
                "可用动作是 get_candidate_bundle、search_grep、"
                "add_resolution_candidate、count_field_candidates 和 final_decision。"
                "每轮可以选择任意 task fields 里的字段；优先处理 pending_fields。"
                "search_grep 的 query 格式固定为 term1 OR term2 OR term3；"
                "只允许用大写 OR 连接多个短关键词，不要用中文“或”、逗号、斜杠或自然语言句子。"
                "count_field_candidates 的 field_name 是要统计候选数量的字段，返回 number；"
                "如果要把这个数字作为另一个字段的证据，下一轮必须调用 "
                "add_resolution_candidate(field_name=目标字段, values=[数字]) 写入候选池。"
                "final_decision 是唯一正常出口；resolved 结果必须引用 candidate_id，"
                "且 candidate_id 必须属于 final_decision.field_name 的候选池，不能直接引用 grep ref。"
            ),
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    if tool_results or tool_results == 0:
        messages.append(
            {
                "role": "user",
                "content": format_resolution_tool_result(tool_results),
            }
        )
    return messages


def format_resolution_tool_result(result: Any) -> str:
    """把 resolution 工具结果压缩成模型下一轮可读片段。"""

    return json.dumps(_to_jsonable(result), ensure_ascii=False)


def _resolution_tool_contract() -> dict[str, Any]:
    return {
        "get_candidate_bundle": {
            "description": "读取指定字段已经写入候选池的候选摘要。",
            "input": {"field_name": "string"},
            "returns": "Candidate[]，每项包含 candidate_id、source_stage、text 和 reason。",
        },
        "search_grep": {
            "description": "同时搜索正文段落和表格行，返回命中的 ref/text；只做确定性子串匹配，不做语义搜索，不返回整张表。",
            "input": {"query": "string"},
            "query_format": "term1 OR term2 OR term3",
            "query_rules": [
                "多个关键词必须用大写 OR 和空格连接，例如：文明模范寝室 OR 文明寝室。",
                "不要使用中文“或”、逗号、顿号、斜杠或自然语言句子。",
                "每个 term 应是文档中可能原样出现的短关键词。",
            ],
            "returns": "SearchResult[]，每项包含 ref 和 text；ref 可传给 add_resolution_candidate。",
        },
        "add_resolution_candidate": {
            "description": "把 resolution 阶段二次搜索得到的 ref，或上一个工具返回的数字/字符串，写入指定字段候选池。",
            "input": {
                "field_name": "目标字段",
                "refs": "可选，search_grep 返回的 ref 列表",
                "values": "可选，count_field_candidates 返回的数字等字符串值列表",
                "reason": "string",
            },
            "returns": "Candidate[]，每项包含 candidate_id、ref、text 和 reason。",
        },
        "count_field_candidates": {
            "description": "统计指定字段候选池里当前已经写入的候选数量，不读取新证据、不修改候选池。",
            "input": {"field_name": "要统计候选数量的字段"},
            "returns": "number。",
        },
        "final_decision": {
            "description": "指定字段 resolution 阶段的唯一正常出口。",
            "input": {
                "field_name": "string",
                "status": "resolved | failed",
                "value": "字段最终值；failed 时必须为空",
                "candidate_ids": "resolved 时必须引用当前字段候选池里的 candidate_id",
                "reason": "resolved 时说明定案依据",
                "failure_reason": "failed 时说明失败原因",
            },
            "rules": [
                "resolved 结果必须引用 candidate_id，不能直接引用 search_grep 返回的 ref。",
                "candidate_id 必须属于当前字段候选池。",
            ],
        },
    }


def _candidate_bundle_for_field(
    *,
    state: GraphState,
    field_name: str,
) -> list[dict[str, Any]]:
    candidates = list(state.candidates.get(field_name, []))
    included_candidates = candidates[
        : state.extraction_input.options.max_resolution_candidates
    ]
    return [
        {
            "candidate_id": candidate.candidate_id,
            "field_name": candidate.field_name,
            "ref": candidate.ref,
            "text": candidate.text,
            "source_stage": candidate.source_stage,
            "reason": candidate.reason,
        }
        for candidate in included_candidates
    ]


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_jsonable(item) for key, item in value.items()}
    return value
