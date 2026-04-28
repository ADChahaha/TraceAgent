"""`service.route_policy_agent` 的对外稳定数据契约。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from service.file_extraction_agent.schemas import FieldDefinition, FieldType, TaskSpec


FieldStatus = Literal["resolved", "failed"]
RouteDecision = Literal["accept", "review", "reject"]
RunStatus = Literal["completed", "failed"]


class PolicyOptions(BaseModel):
    """route policy 阶段的 prompt 和模型调用预算。"""

    model_config = ConfigDict(extra="forbid")

    max_refs_per_field: int = 8
    max_ref_text_chars: int = 1200

    @field_validator("max_refs_per_field", "max_ref_text_chars")
    @classmethod
    def validate_positive_limit(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("policy option limits must be greater than 0")
        return value


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
    policy_options: PolicyOptions = Field(default_factory=PolicyOptions)
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
    "FieldDefinition",
    "FieldRefsWithText",
    "FieldRouteDecision",
    "FieldStatus",
    "FieldType",
    "PolicyOptions",
    "RouteDecision",
    "RouteFieldOutput",
    "RoutePolicyDecision",
    "RoutePolicyInput",
    "RoutePolicyResult",
    "RunStatus",
    "TaskSpec",
]
