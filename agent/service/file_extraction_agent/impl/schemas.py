"""`service.file_extraction_agent` 的内部流程对象。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from service.file_extraction_agent.schemas import (
    FieldStatus,
    NormalizedBlock,
    RunOptions,
    TaskSpec,
)


class ExtractionInput(BaseModel):
    """抽取图的入口输入，由 `input_adapter.py` 统一组装。"""

    blocks: list[NormalizedBlock]
    markdown: str = ""
    md_list: list[str] = Field(default_factory=list)
    task_spec: TaskSpec
    options: RunOptions = Field(default_factory=RunOptions)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchResult(BaseModel):
    """grep 工具返回给模型的最小证据定位。"""

    ref: str
    text: str


CandidateStage = Literal["broad", "resolution"]


class Candidate(BaseModel):
    """模型明确加入候选池的证据。"""

    candidate_id: str
    field_name: str
    source_stage: CandidateStage
    ref: str
    text: str
    reason: str


BroadFinishStatus = Literal["enough_evidence", "partial_evidence", "no_evidence"]


class BroadFinishRecord(BaseModel):
    """单字段 broad loop 的正常退出记录。"""

    field_name: str
    status: BroadFinishStatus
    reason: str


ToolStage = Literal["broad", "resolution", "graph"]


class ToolActionRecord(BaseModel):
    """系统可证明发生过的工具或阶段动作。"""

    field_name: str
    stage: ToolStage
    action_type: str
    message: str | None = None
    refs: list[str] = Field(default_factory=list)
    candidate_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class FieldDecision(BaseModel):
    """resolution 阶段产出的单字段最终定案。"""

    field_name: str
    status: FieldStatus
    value: Any | None = None
    candidate_ids: list[str] = Field(default_factory=list)
    related_fields: list[str] = Field(default_factory=list)
    reason: str | None = None
    failure_reason: str | None = None

    @model_validator(mode="after")
    def validate_status_shape(self) -> "FieldDecision":
        if self.status == "failed":
            if self.value is not None:
                raise ValueError("failed decision must not include value")
            if not self.failure_reason:
                raise ValueError("failed decision requires failure_reason")
            return self

        if self.value is None:
            raise ValueError("resolved decision requires value")
        if not self.candidate_ids:
            raise ValueError("resolved decision requires candidate_ids")
        if not self.reason:
            raise ValueError("resolved decision requires reason")
        return self


BroadActionType = Literal[
    "search_grep",
    "search_text_grep",
    "search_table_rows_grep",
    "add_broad_candidate",
    "finish_broad",
]


class BroadAction(BaseModel):
    """broad 模型单轮返回的动作。"""

    action: BroadActionType
    field_name: str
    query: str | None = None
    refs: list[str] = Field(default_factory=list)
    reason: str | None = None
    status: BroadFinishStatus | None = None
    model_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_action_payload(self) -> "BroadAction":
        if self.action in {"search_grep", "search_text_grep", "search_table_rows_grep"}:
            if not self.query:
                raise ValueError(f"{self.action} action requires query")
            return self
        if self.action == "add_broad_candidate":
            if not self.refs:
                raise ValueError("add_broad_candidate action requires refs")
            if not self.reason:
                raise ValueError("add_broad_candidate action requires reason")
            return self
        if self.status is None or not self.reason:
            raise ValueError("finish_broad action requires status and reason")
        return self


ResolutionActionType = Literal[
    "get_candidate_bundle",
    "search_grep",
    "search_text_grep",
    "search_table_rows_grep",
    "add_resolution_candidate",
    "final_decision",
]
FieldResolutionValue = str | int | float | bool | list[str] | None


class FieldResolutionAction(BaseModel):
    """resolution 模型单轮返回的动作。"""

    action: ResolutionActionType
    field_name: str
    query: str | None = None
    refs: list[str] = Field(default_factory=list)
    status: FieldStatus | None = None
    value: FieldResolutionValue = None
    candidate_ids: list[str] = Field(default_factory=list)
    related_fields: list[str] = Field(default_factory=list)
    reason: str | None = None
    failure_reason: str | None = None
    model_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_action_payload(self) -> "FieldResolutionAction":
        if self.action == "get_candidate_bundle":
            return self
        if self.action in {"search_grep", "search_text_grep", "search_table_rows_grep"}:
            if not self.query:
                raise ValueError(f"{self.action} action requires query")
            return self
        if self.action == "add_resolution_candidate":
            if not self.refs:
                raise ValueError("add_resolution_candidate action requires refs")
            if not self.reason:
                raise ValueError("add_resolution_candidate action requires reason")
            return self

        if self.status is None:
            raise ValueError("final_decision action requires status")
        if self.status == "failed":
            if self.value is not None:
                raise ValueError("failed final_decision must not include value")
            if not self.failure_reason:
                raise ValueError("failed final_decision requires failure_reason")
            return self
        if self.value is None:
            raise ValueError("resolved final_decision requires value")
        if not self.candidate_ids:
            raise ValueError("resolved final_decision requires candidate_ids")
        if not self.reason:
            raise ValueError("resolved final_decision requires reason")
        return self
