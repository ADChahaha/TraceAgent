"""Public schemas for HTML file extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


BasicFieldType = Literal["string", "number", "boolean", "list[string]", "list[number]", "null"]
FieldType = Literal["string", "number", "boolean", "list[string]", "list[number]", "null", "enum"]
ResultStatus = Literal["completed", "failed"]


class EnumVariantDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    type: BasicFieldType
    description: str | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_bool_alias(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("type") == "bool":
            data = dict(data)
            data["type"] = "boolean"
        return data

    @model_validator(mode="after")
    def validate_name(self) -> "EnumVariantDefinition":
        if not self.name:
            raise ValueError("enum variant name is required")
        return self


class FieldDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str
    type: FieldType = "string"
    variants: list[EnumVariantDefinition] = Field(default_factory=list)
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
        if self.type == "enum":
            if not self.variants:
                raise ValueError("enum field requires variants")
            names = [variant.name for variant in self.variants]
            if len(names) != len(set(names)):
                raise ValueError("enum variant names must be unique")
        elif self.variants:
            raise ValueError("variants are only allowed when field type is enum")
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
    resolution_model_name: str = ""
    temperature: float = 0.0
    top_p: float | None = None
    top_k: int | None = None
    reasoning_effort: str | None = None
    max_retries: int = 6
    request_timeout: float | None = None


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
    "BasicFieldType",
    "ResultStatus",
    "EnumVariantDefinition",
    "FieldDefinition",
    "TaskSpec",
    "ModelConfig",
    "RunOptions",
    "EvidenceRef",
    "ExtractionResult",
]
