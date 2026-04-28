"""`service.file_extraction_agent` 的对外稳定数据契约。

这个模块只定义调用方可见的稳定输入输出对象，不直接暴露 broad /
resolution / lookup 这些内部阶段对象。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


FieldType = Literal["string", "date", "enum", "money", "boolean"]
FieldStatus = Literal["resolved", "failed"]
RunStatus = Literal["completed", "failed"]


class RunOptions(BaseModel):
    """抽取运行选项。

    这个对象是调用方、HTTP route 和内部 graph 共用的稳定契约。
    """

    allow_extra_lookup: bool = True
    max_lookup_calls_per_field: int = 1
    lookup_top_k: int = 3
    max_prompt_blocks: int = 200
    max_prompt_block_chars: int = 2000
    max_resolution_evidence_fields: int = 80
    max_prompt_evidence_text_chars: int = 1000
    keep_detailed_trace: bool = False

    @field_validator(
        "max_lookup_calls_per_field",
        "lookup_top_k",
        "max_prompt_blocks",
        "max_prompt_block_chars",
        "max_resolution_evidence_fields",
        "max_prompt_evidence_text_chars",
    )
    @classmethod
    def validate_positive_limit(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("run option limits must be greater than 0")
        return value


class FieldEvidenceRef(BaseModel):
    """字段证据在原始文档中的定位信息，用于前端高亮和审计回溯。"""

    document_id: str
    page: int | None = None
    span: str | None = None
    block_id: str | None = None


class FieldDefinition(BaseModel):
    """固定 schema 中的单字段定义。"""

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
    """一次抽取任务的固定 schema 定义。"""

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
    """标准化 block 的坐标框。"""

    x0: float
    y0: float
    x1: float
    y1: float


class NormalizedBlock(BaseModel):
    """进入 extraction 阶段的标准化块结构。"""

    document_id: str
    block_id: str | None = None
    text: str
    page_no: int | None = None
    bbox: NormalizedBoundingBox | None = None
    kind: str = "text"
    meta_info: dict[str, Any] = Field(default_factory=dict)


class NormalizedDocument(BaseModel):
    """备用的文档级文本结构，不是当前主处理链路的一等输入。"""

    document_id: str
    markdown: str = ""
    md_list: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceSummary(BaseModel):
    """对外 trace 中的字段证据摘要。"""

    block_ids: list[str] = Field(default_factory=list)
    texts: list[str] = Field(default_factory=list)
    refs: list[FieldEvidenceRef] = Field(default_factory=list)
    status: str
    notes: list[str] = Field(default_factory=list)


class TraceAction(BaseModel):
    """对外 trace 中的字段动作记录。"""

    action_type: str
    message: str | None = None
    refs: list[FieldEvidenceRef] = Field(default_factory=list)
    used_in_final_decision: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class FieldResult(BaseModel):
    """顶层 `result` 中的单字段纯业务结果。"""

    field_name: str
    status: FieldStatus
    value: Any | None = None

    @model_validator(mode="after")
    def validate_status_shape(self) -> "FieldResult":
        if self.status == "failed":
            if self.value is not None:
                raise ValueError("failed status must not include value")
        else:
            if self.value is None:
                raise ValueError("resolved status requires value")
        return self


class FieldTrace(BaseModel):
    """顶层 `trace` 中的单字段留痕。"""

    field_name: str
    status: FieldStatus
    evidence: EvidenceSummary
    related_fields: list[str] = Field(default_factory=list)
    actions: list[TraceAction] = Field(default_factory=list)
    reason: str | None = None
    failure_reason: str | None = None

    @model_validator(mode="after")
    def validate_reason_shape(self) -> "FieldTrace":
        if self.status == "resolved":
            if not self.reason:
                raise ValueError("resolved trace requires reason")
        else:
            if not self.failure_reason:
                raise ValueError("failed trace requires failure_reason")
        return self


class ExtractionContent(BaseModel):
    """顶层 `result`：只保存最终字段业务结果。"""

    fields: list[FieldResult]


class ExtractionTrace(BaseModel):
    """顶层 `trace`：保存证据、动作摘要和定案原因。"""

    fields: list[FieldTrace]
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExtractionResult(BaseModel):
    """一次 extraction 运行的最终返回对象。"""

    status: RunStatus = "completed"
    failure_reason: str | None = None
    result: ExtractionContent
    trace: ExtractionTrace

    @model_validator(mode="after")
    def validate_run_status_shape(self) -> "ExtractionResult":
        if self.status == "failed" and not self.failure_reason:
            raise ValueError("failed extraction result requires failure_reason")
        return self
