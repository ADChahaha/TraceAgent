"""file_extraction_agent 图内部执行态。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from service.file_extraction_agent.impl.block_ids import validate_block_ids
from service.file_extraction_agent.impl.schemas import (
    EvidenceCollection,
    ExtractionInput,
    FieldDecision,
)


class GraphState(BaseModel):
    """图运行过程中的共享状态容器。"""

    extraction_input: ExtractionInput
    evidence_collection: EvidenceCollection | None = None
    field_decisions: list[FieldDecision] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def build_graph_state(extraction_input: ExtractionInput) -> GraphState:
    """基于入口 `ExtractionInput` 创建一份空的执行态。"""

    normalized_input = extraction_input.model_copy(
        update={"blocks": validate_block_ids(extraction_input.blocks)}
    )
    return GraphState(extraction_input=normalized_input)
