"""resolution 阶段 prompt 组装。"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from service.file_extraction_agent.impl.state import GraphState
from service.file_extraction_agent.schemas import FieldDefinition


def build_resolution_messages(
    *,
    state: GraphState,
    field: FieldDefinition,
    tool_results: list[Any],
) -> list[dict[str, str]]:
    """构造单字段 resolution loop 的模型输入。"""

    candidates = list(state.candidates.get(field.field_name, []))
    included_candidates = candidates[
        : state.extraction_input.options.max_resolution_candidates
    ]
    payload = {
        "task_name": state.extraction_input.task_spec.task_name,
        "target_field": field.model_dump(),
        "tool_contract": _resolution_tool_contract(),
        "candidate_bundle": [
            {
                "candidate_id": candidate.candidate_id,
                "text": candidate.text,
                "source_stage": candidate.source_stage,
                "reason": candidate.reason,
            }
            for candidate in included_candidates
        ],
        "completed_fields": [
            {
                "field_name": decision.field_name,
                "status": decision.status,
                "value": decision.value,
            }
            for decision in state.field_decisions.values()
        ],
        "prompt_budget": {
            "total_candidate_count": len(candidates),
            "included_candidate_count": len(included_candidates),
            "omitted_candidate_count": max(0, len(candidates) - len(included_candidates)),
            "max_resolution_candidates": state.extraction_input.options.max_resolution_candidates,
        },
    }
    messages = [
        {
            "role": "system",
            "content": (
                "你是 field resolution 阶段，负责输出最终字段定案。"
                "必须返回 FieldResolutionAction。"
                "工具语义必须以 user payload 里的 tool_contract 为准，不能只按函数名猜。"
                "可用动作是 get_candidate_bundle、search_grep、"
                "add_resolution_candidate 和 final_decision。"
                "search_grep 的 query 格式固定为 term1 OR term2 OR term3；"
                "只允许用大写 OR 连接多个短关键词，不要用中文“或”、逗号、斜杠或自然语言句子。"
                "final_decision 是唯一正常出口；resolved 结果必须引用 candidate_id，"
                "不能直接引用 grep ref。"
            ),
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    if tool_results:
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
            "description": "读取当前字段已经写入候选池的候选摘要。",
            "input": {},
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
            "description": "把 resolution 阶段二次搜索得到的 ref 写入当前字段候选池。",
            "input": {"refs": "list[string]", "reason": "string"},
            "returns": "Candidate[]，每项包含 candidate_id、ref、text 和 reason。",
        },
        "final_decision": {
            "description": "当前字段 resolution 阶段的唯一正常出口。",
            "input": {
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


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_jsonable(item) for key, item in value.items()}
    return value
