"""file_extraction_agent 的 broad extraction 节点。"""

from __future__ import annotations

from typing import Any

from file_extraction_agent.impl.prompts import build_broad_extraction_messages
from file_extraction_agent.impl.schemas import EvidenceCollection
from file_extraction_agent.impl.state import GraphState


def run_broad_extraction(
    *,
    state: GraphState,
    extractor_client: Any,
) -> GraphState:
    """执行第一阶段字段证据预选，并把结果写回图状态。"""

    evidence_collection = extractor_client.invoke(
        output_schema=EvidenceCollection,
        messages=build_broad_extraction_messages(state.extraction_input),
    )
    state.evidence_collection = evidence_collection
    return state
