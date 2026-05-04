"""Public schemas for HTML file extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


FieldType = Literal["string", "number", "boolean", "list[string]", "list[number]"]
ResultStatus = Literal["completed", "failed"]


class FieldDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str
    type: FieldType = "string"
    required: bool = False
    description: str | None = None
    field_name: str | None = Field(default=None, exclude=True)
    display_name: str | None = None
    critical: bool = False
    allow_missing: bool = False
    validation_rules: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_field_name(cls, data: Any) -> Any:
        if isinstance(data, dict) and not data.get("name") and data.get("field_name"):
            data = dict(data)
            data["name"] = data["field_name"]
        return data

    @model_validator(mode="after")
    def fill_field_name(self) -> "FieldDefinition":
        if not self.name:
            raise ValueError("field name is required")
        self.field_name = self.name
        return self


class TaskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fields: list[FieldDefinition]
    instructions: str | None = None
    task_name: str | None = None


@dataclass
class ModelConfig:
    provider: str = "openai"
    base_url: str | None = None
    api_key: str | None = None
    broad_model_name: str = ""
    resolution_model_name: str = ""
    temperature: float = 0.0
    top_p: float | None = None
    top_k: int | None = None


@dataclass
class RunOptions:
    max_tool_calls: int = 200


@dataclass
class EvidenceRef:
    element_id: str
    row_id: str | None = None
    column: str | None = None
    quote: str | None = None


@dataclass
class ExtractionResult:
    status: ResultStatus = "completed"
    result: dict[str, Any] = field(default_factory=dict)
    failure_reason: str | None = None
    trace: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "FieldType",
    "ResultStatus",
    "FieldDefinition",
    "TaskSpec",
    "ModelConfig",
    "RunOptions",
    "EvidenceRef",
    "ExtractionResult",
]
