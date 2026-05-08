from __future__ import annotations

import pytest

from service.file_extraction_agent.schemas import (
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


def test_model_config_keeps_stage_model_names_and_sampling_options():
    config = ModelConfig(
        base_url="https://example.com/v1",
        api_key="key",
        broad_model_name="broad",
        resolution_model_name="resolution",
        temperature=0.2,
        top_p=0.9,
        top_k=40,
        max_retries=7,
        request_timeout=90.0,
    )

    assert config.broad_model_name == "broad"
    assert config.resolution_model_name == "resolution"
    assert config.temperature == 0.2
    assert config.top_p == 0.9
    assert config.top_k == 40
    assert config.max_retries == 7
    assert config.request_timeout == 90.0


def test_run_options_defaults_to_tool_budget_only():
    assert RunOptions().max_tool_calls == 200


def test_extraction_result_defaults_to_completed_empty_payload():
    result = ExtractionResult()

    assert result.status == "completed"
    assert result.result == {}
    assert result.trace == {}
