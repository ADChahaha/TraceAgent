"""file_extraction_agent 的共享数据契约。

这个模块只定义“接受什么输入、产出什么结果”，不描述具体执行流程。

当前约束：

- `GraphInput` 表示抽取图的入口输入，必须带 `session_id`、`documents`、`task_spec`
- `NormalizedDocument` 表示 session 内的单份文档，至少带 `document_id`，并承载标准化后的 `markdown`、`md_list`、`blocks`
- `NormalizedBlock` 表示单个块级内容，明确约束 `text`、`page_no`、`bbox`、`kind`、`meta_info`
- `BroadExtractionOutput` / `BroadExtractionFieldOutput` 表示第一阶段的字段候选、证据和局部状态
- `ResolvedFieldOutput` 表示单字段最终定案结果，只允许 `resolved` 或 `failed`
- `ExtractionResult` 表示最终聚合结果，统一收口 broad output、resolved fields 和 run trace
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


FieldType = Literal["string", "date", "enum", "money", "boolean"]
ResolvedStatus = Literal["resolved", "failed"]


class FieldEvidenceRef(BaseModel):
    document_id: str
    page: int | None = None
    span: str | None = None
    block_id: str | None = None


class FieldDefinition(BaseModel):
    field_name: str
    display_name: str
    type: FieldType
    required: bool = False
    critical: bool = False
    allow_missing: bool = False
    validation_rules: dict[str, Any] = Field(default_factory=dict)
    cross_field_hints: list[str] = Field(default_factory=list)
    lookup_hints: list[str] = Field(default_factory=list)
    enum_values: list[str] = Field(default_factory=list)


class TaskSpec(BaseModel):
    task_name: str | None = None
    fields: list[FieldDefinition]

    @field_validator("fields")
    @classmethod
    def validate_unique_field_names(
        cls, fields: list[FieldDefinition]
    ) -> list[FieldDefinition]:
        seen: set[str] = set()
        duplicated: set[str] = set()
        for field in fields:
            if field.field_name in seen:
                duplicated.add(field.field_name)
            seen.add(field.field_name)
        if duplicated:
            duplicated_names = ", ".join(sorted(duplicated))
            raise ValueError(f"duplicated field_name: {duplicated_names}")
        return fields


class NormalizedBoundingBox(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float


class NormalizedBlock(BaseModel):
    text: str
    page_no: int | None = None
    bbox: NormalizedBoundingBox | None = None
    kind: str = "text"
    meta_info: dict[str, Any] = Field(default_factory=dict)


class NormalizedDocument(BaseModel):
    document_id: str
    markdown: str = ""
    md_list: list[str] = Field(default_factory=list)
    blocks: list[NormalizedBlock] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunConfig(BaseModel):
    allow_extra_lookup: bool = True
    max_extra_lookups_per_field: int = 1
    keep_detailed_trace: bool = False

    @field_validator("max_extra_lookups_per_field")
    @classmethod
    def validate_lookup_limit(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("max_extra_lookups_per_field must be greater than 0")
        return value


class GraphInput(BaseModel):
    session_id: str
    documents: list[NormalizedDocument]
    task_spec: TaskSpec
    run_config: RunConfig = Field(default_factory=RunConfig)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BroadExtractionFieldOutput(BaseModel):
    field_name: str
    candidate_values: list[Any] = Field(default_factory=list)
    evidence_texts: list[str] = Field(default_factory=list)
    evidence_refs: list[FieldEvidenceRef] = Field(default_factory=list)
    local_status: str
    local_validation: dict[str, Any] = Field(default_factory=dict)
    local_notes: list[str] = Field(default_factory=list)


class BroadExtractionOutput(BaseModel):
    fields: list[BroadExtractionFieldOutput]


class ResolvedFieldOutput(BaseModel):
    field_name: str
    status: ResolvedStatus
    final_value: Any | None = None
    used_field_outputs: list[str] = Field(default_factory=list)
    extra_lookup_used: bool = False
    reason: str | None = None
    failure_reason: str | None = None

    @model_validator(mode="after")
    def validate_status_shape(self) -> "ResolvedFieldOutput":
        if self.status == "failed":
            if self.final_value is not None:
                raise ValueError("failed status must not include final_value")
            if not self.failure_reason:
                raise ValueError("failed status requires failure_reason")
        else:
            if self.final_value is None:
                raise ValueError("resolved status requires final_value")
        return self


class RunTrace(BaseModel):
    rounds: int = 1
    lookup_trace: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("rounds")
    @classmethod
    def validate_rounds(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("rounds must be greater than 0")
        return value


class ExtractionResult(BaseModel):
    broad_output: BroadExtractionOutput
    resolved_fields: list[ResolvedFieldOutput]
    run_trace: RunTrace = Field(default_factory=RunTrace)
