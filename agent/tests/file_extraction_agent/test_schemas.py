from __future__ import annotations

import pytest

from service.file_extraction_agent.schemas import (
    EnumVariantDefinition,
    ExtractionResult,
    FieldDefinition,
    ModelConfig,
    RunOptions,
    TaskSpec,
)


def test_task_spec_normalizes_field_dicts():
    task_spec = TaskSpec(
        fields=[
            {"name": "title", "type": "string", "required": True},
            FieldDefinition(name="rooms", type="list[string]"),
        ],
        instructions="Extract the document.",
    )

    assert task_spec.fields[0].name == "title"
    assert task_spec.fields[0].required is True
    assert task_spec.fields[1].name == "rooms"
    assert task_spec.instructions == "Extract the document."


def test_field_definition_rejects_untyped_list():
    with pytest.raises(ValueError):
        FieldDefinition(name="rooms", type="list")


def test_field_definition_accepts_tagged_enum_variants_with_basic_payload_types():
    field = FieldDefinition(
        name="answer",
        type="enum",
        variants=[
            {"name": "text", "type": "string"},
            {"name": "score", "type": "number"},
            {"name": "flags", "type": "list[string]"},
            {"name": "amounts", "type": "list[number]"},
            {"name": "confirmed", "type": "bool"},
            {"name": "missing", "type": "null"},
        ],
    )

    assert [variant.name for variant in field.variants] == [
        "text",
        "score",
        "flags",
        "amounts",
        "confirmed",
        "missing",
    ]
    assert [variant.type for variant in field.variants] == [
        "string",
        "number",
        "list[string]",
        "list[number]",
        "boolean",
        "null",
    ]


def test_field_definition_rejects_invalid_enum_shapes():
    with pytest.raises(ValueError):
        FieldDefinition(name="answer", type="enum")
    with pytest.raises(ValueError):
        FieldDefinition(
            name="answer",
            type="enum",
            variants=[{"name": "text", "type": "object"}],
        )
    with pytest.raises(ValueError):
        FieldDefinition(
            name="answer",
            type="enum",
            variants=[
                {"name": "text", "type": "string"},
                {"name": "text", "type": "number"},
            ],
        )
    with pytest.raises(ValueError):
        FieldDefinition(
            name="answer",
            type="string",
            variants=[EnumVariantDefinition(name="text", type="string")],
        )


def test_model_config_keeps_stage_model_names_and_sampling_options():
    config = ModelConfig(
        base_url="https://example.com/v1",
        api_key="key",
        resolution_model_name="resolution",
        temperature=0.2,
        top_p=0.9,
        top_k=40,
        reasoning_effort="high",
        max_retries=7,
        request_timeout=90.0,
    )

    assert config.resolution_model_name == "resolution"
    assert config.temperature == 0.2
    assert config.top_p == 0.9
    assert config.top_k == 40
    assert config.reasoning_effort == "high"
    assert config.max_retries == 7
    assert config.request_timeout == 90.0


def test_run_options_defaults_to_tool_budget_only():
    assert RunOptions().max_tool_calls == 200


def test_extraction_result_defaults_to_completed_empty_payload():
    result = ExtractionResult()

    assert result.status == "completed"
    assert result.result == {}
    assert result.trace == {}
