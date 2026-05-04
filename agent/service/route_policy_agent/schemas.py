"""`service.route_policy_agent` 的对外稳定数据契约。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from service.file_extraction_agent.schemas import FieldDefinition, FieldType, TaskSpec


FieldStatus = Literal["resolved", "failed"]
RouteDecision = Literal["accept", "review", "reject"]
RunStatus = Literal["completed", "failed"]


class EvidenceTextRef(BaseModel):
    """带证据文本的字段 ref，供 route policy 独立判断字段值是否被支持。"""

    model_config = ConfigDict(extra="forbid")

    document_id: str | None = None
    page: int | None = None
    block_id: str | None = None
    span: str | None = None
    text: str = ""


class FieldRefsWithText(BaseModel):
    """单字段对应的一组带文本 refs。"""

    model_config = ConfigDict(extra="forbid")

    field_name: str
    refs: list[EvidenceTextRef] = Field(default_factory=list)


class CountedFieldSummary(BaseModel):
    """count_field_candidates 的可见摘要，不包含工具返回正文或 refs。"""

    model_config = ConfigDict(extra="forbid")

    field_name: str
    count: int

    @field_validator("field_name")
    @classmethod
    def validate_field_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("field_name is required")
        return value

    @field_validator("count")
    @classmethod
    def validate_count(cls, value: int) -> int:
        if value < 0:
            raise ValueError("count must not be negative")
        return value


class QualityDiagnosticIssue(BaseModel):
    """工具质量诊断中的单条风险摘要，不携带原始 row/cell 内容。"""

    model_config = ConfigDict(extra="forbid")

    code: str
    severity: str = "warning"
    message: str
    row_id: str | None = None
    row_ids: list[str] = Field(default_factory=list)

    @field_validator("code", "severity", "message")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("diagnostic text fields must not be empty")
        return value.strip()


class QualityDiagnosticSummary(BaseModel):
    """route policy 可见的轻量工具观察摘要。"""

    model_config = ConfigDict(extra="forbid")

    source: str
    quality_type: str
    issues: list[QualityDiagnosticIssue] = Field(default_factory=list)
    table_id: str | None = None
    query: str | None = None
    summary: str | None = None

    @field_validator("source", "quality_type")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("diagnostic summary text fields must not be empty")
        return value.strip()

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("diagnostic summary must not be empty")
        return value.strip()


class RouteProcessStage(BaseModel):
    """route policy 可见的单阶段抽取过程摘要。"""

    model_config = ConfigDict(extra="forbid")

    status: str | None = None
    search_queries: list[str] = Field(default_factory=list)
    candidate_action_count: int = 0
    counted_fields: list[CountedFieldSummary] = Field(default_factory=list)
    finish_reason: str | None = None
    final_decision_used: bool = False
    reason: str | None = None
    failure_reason: str | None = None
    diagnostics: list[QualityDiagnosticSummary] = Field(default_factory=list)

    @field_validator("search_queries")
    @classmethod
    def validate_search_queries(cls, value: list[str]) -> list[str]:
        stripped = [item.strip() for item in value if item.strip()]
        if len(stripped) != len(value):
            raise ValueError("search_queries must not contain empty items")
        return stripped

    @field_validator("candidate_action_count")
    @classmethod
    def validate_candidate_action_count(cls, value: int) -> int:
        if value < 0:
            raise ValueError("candidate_action_count must not be negative")
        return value


class RouteFieldProcess(BaseModel):
    """单字段 broad / resolution 两阶段过程摘要。"""

    model_config = ConfigDict(extra="forbid")

    field_name: str
    broad_extraction: RouteProcessStage
    field_resolution: RouteProcessStage


class RouteFieldOutput(BaseModel):
    """route policy 只消费字段最终输出，不消费抽取 trace。"""

    model_config = ConfigDict(extra="forbid")

    field_name: str
    status: FieldStatus
    value: Any | None = None

    @model_validator(mode="after")
    def validate_status_shape(self) -> "RouteFieldOutput":
        if self.status == "failed":
            if self.value is not None:
                raise ValueError("failed field output must not include value")
        elif self.value is None:
            raise ValueError("resolved field output requires value")
        return self


class RoutePolicyInput(BaseModel):
    """route policy 阶段入口输入。"""

    model_config = ConfigDict(extra="forbid")

    task_spec: TaskSpec
    field_outputs: list[RouteFieldOutput]
    refs_with_text: list[FieldRefsWithText]
    field_processes: list[RouteFieldProcess]
    metadata: dict[str, Any] = Field(default_factory=dict)


class RoutePolicyDecision(BaseModel):
    """小 LLM 对单字段返回的严格结构化 route 决策。"""

    model_config = ConfigDict(extra="forbid")

    route: RouteDecision
    route_reason: str

    @field_validator("route_reason")
    @classmethod
    def validate_route_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("route_reason is required")
        return value


class FieldRouteDecision(BaseModel):
    """对外返回的单字段 route 结果。"""

    model_config = ConfigDict(extra="forbid")

    field_name: str
    route: RouteDecision
    route_reason: str
    needs_review: bool | None = None

    @model_validator(mode="after")
    def fill_needs_review(self) -> "FieldRouteDecision":
        expected = self.route != "accept"
        if self.needs_review is None:
            self.needs_review = expected
        elif self.needs_review != expected:
            raise ValueError("needs_review must be false only when route is accept")
        return self


class RoutePolicyResult(BaseModel):
    """一次 route policy 运行的最终返回对象。"""

    model_config = ConfigDict(extra="forbid")

    status: RunStatus = "completed"
    failure_reason: str | None = None
    field_routes: list[FieldRouteDecision] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_run_status_shape(self) -> "RoutePolicyResult":
        if self.status == "failed" and not self.failure_reason:
            raise ValueError("failed route policy result requires failure_reason")
        return self


__all__ = [
    "EvidenceTextRef",
    "CountedFieldSummary",
    "FieldDefinition",
    "FieldRefsWithText",
    "FieldRouteDecision",
    "FieldStatus",
    "FieldType",
    "QualityDiagnosticIssue",
    "QualityDiagnosticSummary",
    "RouteFieldProcess",
    "RouteDecision",
    "RouteFieldOutput",
    "RoutePolicyDecision",
    "RoutePolicyInput",
    "RoutePolicyResult",
    "RouteProcessStage",
    "RunStatus",
    "TaskSpec",
]
