"""file_extraction_agent 的内部 graph 编排层。"""

from __future__ import annotations

from typing import Any

from file_extraction_agent.impl.broad_extraction import run_broad_extraction
from file_extraction_agent.impl.resolution import run_resolution
from file_extraction_agent.impl.schemas import ExtractionInput
from file_extraction_agent.impl.state import build_graph_state
from file_extraction_agent.schemas import (
    ExtractionContent,
    ExtractionResult,
    ExtractionTrace,
)


def run_extraction_graph(
    *,
    extraction_input: ExtractionInput,
    extractor_client: Any,
) -> ExtractionResult:
    """串联 broad extraction 与 resolution 两个内部节点。"""

    state = build_graph_state(extraction_input)
    state = run_broad_extraction(state=state, extractor_client=extractor_client)
    state = run_resolution(state=state, extractor_client=extractor_client)

    if state.evidence_collection is None:
        raise ValueError("graph finished without evidence_collection")

    return ExtractionResult(
        result=ExtractionContent(
            fields=[field_decision.to_field_result() for field_decision in state.field_decisions]
        ),
        trace=ExtractionTrace(
            fields=[field_decision.to_field_trace() for field_decision in state.field_decisions],
            warnings=state.warnings,
        ),
    )
