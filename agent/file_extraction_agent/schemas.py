"""`file_extraction_agent` 的共享数据契约。

这个模块只定义“接受什么输入、产出什么结果”，不描述具体执行流程。

实现链路可以按下面理解：

```text
调用方传入 backend 聚合后的 blocks 和 task_spec
  -> GraphInput 固定一次 extraction 会话的主输入
  -> broad extraction 为每个字段产出 FieldEvidenceBundle
  -> resolution 产出纯结果 ResolvedFieldResult
  -> 同时把 broad / cross / lookup / reason 收口进 FieldTraceRecord
  -> processor 返回 ExtractionResult(result + trace)
```

注意：broad 阶段只做证据预选，不再定义 `candidate_values`。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


FieldType = Literal["string", "date", "enum", "money", "boolean"]
ResolvedStatus = Literal["resolved", "failed"]


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


class RunConfig(BaseModel):
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


class GraphInput(BaseModel):
    """抽取图的入口输入，由 `input_adapter.py` 统一组装。"""

    blocks: list[NormalizedBlock]
    markdown: str = ""
    md_list: list[str] = Field(default_factory=list)
    task_spec: TaskSpec
    run_config: RunConfig = Field(default_factory=RunConfig)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BroadTrace(BaseModel):
    """broad 阶段的字段级证据预选痕迹。"""

    relevant_block_ids: list[str] = Field(default_factory=list)
    evidence_texts: list[str] = Field(default_factory=list)
    evidence_refs: list[FieldEvidenceRef] = Field(default_factory=list)
    local_status: str
    local_notes: list[str] = Field(default_factory=list)


class FieldEvidenceBundle(BaseModel):
    """broad 阶段输出的字段级 evidence bundle。"""

    field_name: str
    relevant_block_ids: list[str] = Field(default_factory=list)
    evidence_texts: list[str] = Field(default_factory=list)
    evidence_refs: list[FieldEvidenceRef] = Field(default_factory=list)
    local_status: str
    local_notes: list[str] = Field(default_factory=list)

    def to_broad_trace(self) -> BroadTrace:
        """把 broad 输出投影成最终 trace 使用的 `broad_trace`。"""

        return BroadTrace(
            relevant_block_ids=list(self.relevant_block_ids),
            evidence_texts=list(self.evidence_texts),
            evidence_refs=list(self.evidence_refs),
            local_status=self.local_status,
            local_notes=list(self.local_notes),
        )


class BroadExtractionOutput(BaseModel):
    """broad 阶段的整体输出。"""

    fields: list[FieldEvidenceBundle]


class ResolvedFieldResult(BaseModel):
    """`result` 中的单字段纯业务结果。"""

    field_name: str
    status: ResolvedStatus
    final_value: Any | None = None

    @model_validator(mode="after")
    def validate_status_shape(self) -> "ResolvedFieldResult":
        if self.status == "failed":
            if self.final_value is not None:
                raise ValueError("failed status must not include final_value")
        else:
            if self.final_value is None:
                raise ValueError("resolved status requires final_value")
        return self


class LookupTraceRecord(BaseModel):
    """单次全局补查留下的字段级 trace。"""

    target_field_name: str | None = None
    lookup_reason: str
    lookup_hints: list[str] = Field(default_factory=list)
    returned_block_ids: list[str] = Field(default_factory=list)
    returned_refs: list[FieldEvidenceRef] = Field(default_factory=list)
    used_in_final_decision: bool = False


class FieldTraceRecord(BaseModel):
    """`trace` 中的单字段记录。"""

    field_name: str
    status: ResolvedStatus
    broad_trace: BroadTrace
    used_field_outputs: list[str] = Field(default_factory=list)
    extra_lookup_used: bool = False
    lookup_trace: list[LookupTraceRecord] = Field(default_factory=list)
    reason: str | None = None
    failure_reason: str | None = None

    @model_validator(mode="after")
    def validate_reason_shape(self) -> "FieldTraceRecord":
        if self.status == "resolved":
            if not self.reason:
                raise ValueError("resolved trace requires reason")
        else:
            if not self.failure_reason:
                raise ValueError("failed trace requires failure_reason")
        return self


class ExtractionContent(BaseModel):
    """顶层 `result`：只保存最终字段业务结果。"""

    fields: list[ResolvedFieldResult]


class ExtractionTrace(BaseModel):
    """顶层 `trace`：保存 broad / cross / lookup / reason 等留痕。"""

    fields: list[FieldTraceRecord]
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExtractionResult(BaseModel):
    """一次 extraction 运行的最终返回对象。"""

    result: ExtractionContent
    trace: ExtractionTrace
