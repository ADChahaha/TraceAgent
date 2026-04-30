"""broad 和 resolution 共用的确定性 grep 搜索工具。"""

from __future__ import annotations

import re

from service.file_extraction_agent.impl.schemas import SearchResult, ToolActionRecord
from service.file_extraction_agent.impl.state import GraphState, record_action


def search_grep(
    *,
    state: GraphState,
    field_name: str,
    query: str,
    stage: str = "broad",
) -> list[SearchResult]:
    """同时搜索正文段落和表格行，按原文索引顺序返回命中。"""

    query_terms = _query_terms(query)
    results = [
        *_search_index(state.paragraph_index, query_terms=query_terms),
        *_search_index(state.table_row_index, query_terms=query_terms),
    ]
    record_action(
        state,
        field_name=field_name,
        action=ToolActionRecord(
            field_name=field_name,
            stage=stage,
            action_type="search_grep",
            message=query,
            refs=[item.ref for item in results],
            metadata={
                "query_terms": query_terms,
                "searched_indexes": ["paragraph", "table_row"],
            },
        ),
    )
    return results


def search_text_grep(
    *,
    state: GraphState,
    field_name: str,
    query: str,
    stage: str = "broad",
) -> list[SearchResult]:
    """在文本段落索引中按原文顺序做字符串匹配。"""

    query_terms = _query_terms(query)
    results = _search_index(state.paragraph_index, query_terms=query_terms)
    record_action(
        state,
        field_name=field_name,
        action=ToolActionRecord(
            field_name=field_name,
            stage=stage,
            action_type="text_grep",
            message=query,
            refs=[item.ref for item in results],
            metadata={"query_terms": query_terms},
        ),
    )
    return results


def search_table_rows_grep(
    *,
    state: GraphState,
    field_name: str,
    query: str,
    stage: str = "broad",
) -> list[SearchResult]:
    """在表格行索引中按原文顺序做字符串匹配。"""

    query_terms = _query_terms(query)
    results = _search_index(state.table_row_index, query_terms=query_terms)
    record_action(
        state,
        field_name=field_name,
        action=ToolActionRecord(
            field_name=field_name,
            stage=stage,
            action_type="table_row_grep",
            message=query,
            refs=[item.ref for item in results],
            metadata={"query_terms": query_terms},
        ),
    )
    return results


def _search_index(index, *, query_terms: list[str]) -> list[SearchResult]:
    normalized_terms = [term.casefold() for term in query_terms if term]
    if not normalized_terms:
        return []
    return [
        SearchResult(ref=ref, text=source.text)
        for ref, source in index.items()
        if any(term in source.text.casefold() for term in normalized_terms)
    ]


def _query_terms(query: str) -> list[str]:
    return [
        term.strip()
        for term in re.split(r"\s+OR\s+", query)
        if term.strip()
    ]
