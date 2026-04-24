"""`file_extraction_agent` 的内部流程对象。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from file_extraction_agent.schemas import (
    EvidenceSummary,
    FieldEvidenceRef,
    FieldResult,
    FieldStatus,
    FieldTrace,
    NormalizedBlock,
    TaskSpec,
    TraceAction,
)


class RunOptions(BaseModel):
    """图执行阶段的运行配置。"""

    allow_extra_lookup: bool = True
    max_extra_lookups_per_field: int = 1
    keep_detailed_trace: bool = False

    @field_validator("max_extra_lookups_per_field")
    @classmethod
    def validate_lookup_limit(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("max_extra_lookups_per_field must be greater than 0")
        return value


class ExtractionInput(BaseModel):
    """抽取图的入口输入，由 `input_adapter.py` 统一组装。"""

    blocks: list[NormalizedBlock]
    markdown: str = ""
    md_list: list[str] = Field(default_factory=list)
    task_spec: TaskSpec
    options: RunOptions = Field(default_factory=RunOptions)
    metadata: dict[str, Any] = Field(default_factory=dict)


class FieldEvidence(BaseModel):
    """broad 阶段输出的单字段证据。"""

    field_name: str
    relevant_block_ids: list[str] = Field(default_factory=list)
    evidence_texts: list[str] = Field(default_factory=list)
    evidence_refs: list[FieldEvidenceRef] = Field(default_factory=list)
    local_status: str
    local_notes: list[str] = Field(default_factory=list)

    def to_evidence_summary(self) -> EvidenceSummary:
        return EvidenceSummary(
            block_ids=list(self.relevant_block_ids),
            texts=list(self.evidence_texts),
            refs=list(self.evidence_refs),
            status=self.local_status,
            notes=list(self.local_notes),
        )


class EvidenceCollection(BaseModel):
    """broad 阶段的整体输出。"""

    fields: list[FieldEvidence]


class LookupRecord(BaseModel):
    """单次补查留下的内部记录。"""

    target_field_name: str | None = None
    lookup_reason: str
    lookup_hints: list[str] = Field(default_factory=list)
    returned_block_ids: list[str] = Field(default_factory=list)
    returned_refs: list[FieldEvidenceRef] = Field(default_factory=list)
    used_in_final_decision: bool = False

    def to_trace_action(self) -> TraceAction:
        return TraceAction(
            action_type="global_lookup",
            message=self.lookup_reason,
            refs=list(self.returned_refs),
            used_in_final_decision=self.used_in_final_decision,
        )


class LookupResult(BaseModel):
    """一次补查工具调用返回的内部结果。"""

    matched_blocks: list[NormalizedBlock] = Field(default_factory=list)
    record: LookupRecord


class FieldDecision(BaseModel):
    """resolution 阶段的单字段内部定案对象。"""

    field_name: str
    status: FieldStatus
    value: Any | None = None
    evidence: FieldEvidence
    related_fields: list[str] = Field(default_factory=list)
    lookup_records: list[LookupRecord] = Field(default_factory=list)
    reason: str | None = None
    failure_reason: str | None = None

    @model_validator(mode="after")
    def validate_status_shape(self) -> "FieldDecision":
        if self.status == "failed":
            if self.value is not None:
                raise ValueError("failed status must not include value")
            if not self.failure_reason:
                raise ValueError("failed decision requires failure_reason")
        else:
            if self.value is None:
                raise ValueError("resolved status requires value")
            if not self.reason:
                raise ValueError("resolved decision requires reason")
        return self

    def to_field_result(self) -> FieldResult:
        return FieldResult(
            field_name=self.field_name,
            status=self.status,
            value=self.value,
        )

    def to_field_trace(self) -> FieldTrace:
        return FieldTrace(
            field_name=self.field_name,
            status=self.status,
            evidence=self.evidence.to_evidence_summary(),
            related_fields=list(self.related_fields),
            actions=[record.to_trace_action() for record in self.lookup_records],
            reason=self.reason,
            failure_reason=self.failure_reason,
        )


ResolutionAction = Literal["final_decision", "get_field_bundle", "lookup_blocks"]


class FieldResolutionAction(BaseModel):
    """resolution 模型单轮返回的内部动作。"""

    action: ResolutionAction
    target_field_name: str
    decision: FieldDecision | None = None
    requested_field_name: str | None = None
    query_reason: str | None = None
    lookup_hints: list[str] = Field(default_factory=list)
    model_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_action_payload(self) -> "FieldResolutionAction":
        if self.action == "final_decision":
            if self.decision is None:
                raise ValueError("final_decision action requires decision")
            if self.decision.field_name != self.target_field_name:
                raise ValueError("decision.field_name must match target_field_name")
            return self

        if self.decision is not None:
            raise ValueError("tool request action must not include decision")
        if self.action == "get_field_bundle" and not self.requested_field_name:
            raise ValueError("get_field_bundle action requires requested_field_name")
        if self.action == "lookup_blocks" and not self.query_reason:
            raise ValueError("lookup_blocks action requires query_reason")
        return self
