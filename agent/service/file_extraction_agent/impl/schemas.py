"""`service.file_extraction_agent` 的内部流程对象。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from service.file_extraction_agent.schemas import (
    EvidenceSummary,
    FieldEvidenceRef,
    FieldResult,
    FieldStatus,
    FieldTrace,
    NormalizedBlock,
    RunOptions,
    TaskSpec,
    TraceAction,
)


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
    returned_to_model: bool = False
    used_in_final_decision: bool = False

    def to_trace_action(self) -> TraceAction:
        return TraceAction(
            action_type="global_lookup",
            message=self.lookup_reason,
            refs=list(self.returned_refs),
            used_in_final_decision=self.used_in_final_decision,
            metadata={
                "target_field_name": self.target_field_name,
                "lookup_hints": list(self.lookup_hints),
                "returned_block_ids": list(self.returned_block_ids),
                "returned_to_model": self.returned_to_model,
            },
        )


class FieldReferenceRecord(BaseModel):
    """一次跨字段 evidence bundle 读取留下的内部记录。"""

    target_field_name: str
    requested_field_name: str
    found: bool = False
    returned_refs: list[FieldEvidenceRef] = Field(default_factory=list)
    returned_to_model: bool = False
    used_in_final_decision: bool = False

    def to_trace_action(self) -> TraceAction:
        message = (
            f"模型请求参考字段 {self.requested_field_name}"
            if self.found
            else f"模型请求参考字段 {self.requested_field_name}，但未找到对应 evidence bundle"
        )
        return TraceAction(
            action_type="field_reference",
            message=message,
            refs=list(self.returned_refs),
            used_in_final_decision=self.used_in_final_decision,
            metadata={
                "target_field_name": self.target_field_name,
                "requested_field_name": self.requested_field_name,
                "found": self.found,
                "returned_to_model": self.returned_to_model,
            },
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
    field_reference_records: list[FieldReferenceRecord] = Field(default_factory=list)
    lookup_records: list[LookupRecord] = Field(default_factory=list)
    trace_actions: list[TraceAction] = Field(default_factory=list)
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
            actions=[
                *[record.to_trace_action() for record in self.field_reference_records],
                *[record.to_trace_action() for record in self.lookup_records],
                *list(self.trace_actions),
            ],
            reason=self.reason,
            failure_reason=self.failure_reason,
        )


ResolutionAction = Literal["final_decision", "get_field_bundle", "lookup_blocks"]
FieldResolutionValue = str | int | float | bool | list[str] | None


class FieldResolutionDecision(BaseModel):
    """resolution 模型返回的轻量字段判断。"""

    status: FieldStatus
    value: FieldResolutionValue = None
    used_block_ids: list[str] = Field(default_factory=list)
    related_fields: list[str] = Field(default_factory=list)
    reason: str | None = None
    failure_reason: str | None = None

    @model_validator(mode="after")
    def validate_status_shape(self) -> "FieldResolutionDecision":
        if self.status == "failed":
            if self.value is not None:
                raise ValueError("failed resolution decision must not include value")
            if not self.failure_reason:
                raise ValueError("failed resolution decision requires failure_reason")
        else:
            if self.value is None:
                raise ValueError("resolved resolution decision requires value")
            if not self.reason:
                raise ValueError("resolved resolution decision requires reason")
        return self


class FieldResolutionAction(BaseModel):
    """resolution 模型单轮返回的内部动作。"""

    action: ResolutionAction
    target_field_name: str
    decision: FieldResolutionDecision | None = None
    requested_field_name: str | None = None
    query_reason: str | None = None
    lookup_hints: list[str] = Field(default_factory=list)
    model_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_action_payload(self) -> "FieldResolutionAction":
        if self.action == "final_decision":
            if self.decision is None:
                raise ValueError("final_decision action requires decision")
            return self

        if self.decision is not None:
            raise ValueError("tool request action must not include decision")
        if self.action == "get_field_bundle" and not self.requested_field_name:
            raise ValueError("get_field_bundle action requires requested_field_name")
        if self.action == "lookup_blocks" and not self.query_reason:
            raise ValueError("lookup_blocks action requires query_reason")
        return self
