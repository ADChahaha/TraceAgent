"""broad 阶段 prompt 组装。"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from service.file_extraction_agent.impl.state import GraphState
from service.file_extraction_agent.schemas import FieldDefinition


def build_broad_messages(
    *,
    state: GraphState,
    field: FieldDefinition,
    tool_results: list[Any],
) -> list[dict[str, str]]:
    """构造单字段 broad loop 的模型输入。"""

    sample_paragraphs = _sample_index(
        state.paragraph_index,
        max_items=state.extraction_input.options.max_prompt_blocks,
        max_chars=state.extraction_input.options.max_prompt_block_chars,
    )
    payload = {
        "task_name": state.extraction_input.task_spec.task_name,
        "field": field.model_dump(),
        "metadata": state.extraction_input.metadata,
        "tool_contract": _broad_tool_contract(),
        "searchable_summary": {
            "paragraph_count": len(state.paragraph_index),
            "table_row_count": len(state.table_row_index),
        },
        "sample_paragraphs": sample_paragraphs,
        "current_candidates": [
            candidate.model_dump()
            for candidate in state.candidates.get(field.field_name, [])
        ],
        "prompt_budget": {
            "included_paragraph_count": len(sample_paragraphs),
            "omitted_paragraph_count": max(0, len(state.paragraph_index) - len(sample_paragraphs)),
            "max_prompt_blocks": state.extraction_input.options.max_prompt_blocks,
            "max_prompt_block_chars": state.extraction_input.options.max_prompt_block_chars,
        },
    }
    messages = [
        {
            "role": "system",
            "content": (
                "你是 broad 阶段，只负责为当前字段召回候选证据。"
                "必须返回 BroadAction。"
                "工具语义必须以 user payload 里的 tool_contract 为准，不能只按函数名猜。"
                "可用动作是 search_grep、add_broad_candidate 和 finish_broad。"
                "search_grep 的 query 格式固定为 term1 OR term2 OR term3；"
                "只允许用大写 OR 连接多个短关键词，不要用中文“或”、逗号、斜杠或自然语言句子。"
                "finish_broad 是唯一正常出口，不能输出字段最终值。"
            ),
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    if tool_results:
        messages.append(
            {
                "role": "user",
                "content": format_broad_tool_result(tool_results),
            }
        )
    return messages


def format_broad_tool_result(result: Any) -> str:
    """把工具结果压缩成模型下一轮可读片段。"""

    return json.dumps(_to_jsonable(result), ensure_ascii=False)


def _broad_tool_contract() -> dict[str, Any]:
    return {
        "search_grep": {
            "description": "同时搜索正文段落和表格行，返回命中的 ref/text；只做确定性子串匹配，不做语义搜索，不返回整张表。",
            "input": {"query": "string"},
            "query_format": "term1 OR term2 OR term3",
            "query_rules": [
                "多个关键词必须用大写 OR 和空格连接，例如：文明模范寝室 OR 文明寝室。",
                "不要使用中文“或”、逗号、顿号、斜杠或自然语言句子。",
                "每个 term 应是文档中可能原样出现的短关键词。",
            ],
            "returns": "SearchResult[]，每项包含 ref 和 text；ref 可传给 add_broad_candidate。",
        },
        "add_broad_candidate": {
            "description": "把 search_grep 返回的 ref 写入当前字段候选池。",
            "input": {"refs": "list[string]", "reason": "string"},
            "returns": "Candidate[]，每项包含 candidate_id、ref、text 和 reason。",
        },
        "finish_broad": {
            "description": "当前字段 broad 阶段的唯一正常出口。",
            "input": {
                "status": "enough_evidence | partial_evidence | no_evidence",
                "reason": "string",
            },
            "rules": [
                "status=enough_evidence 时当前字段必须已经有候选。",
                "finish_broad 不能输出最终字段值。",
            ],
        },
    }


def _sample_index(index, *, max_items: int, max_chars: int) -> list[dict[str, str]]:
    samples: list[dict[str, str]] = []
    for ref, source in list(index.items())[:max_items]:
        samples.append({"ref": ref, "text": source.text[:max_chars]})
    return samples


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_jsonable(item) for key, item in value.items()}
    return value
