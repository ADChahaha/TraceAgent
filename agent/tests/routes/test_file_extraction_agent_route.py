from __future__ import annotations

from fastapi.testclient import TestClient

from main import create_app
from service.file_extraction_agent.schemas import ExtractionResult, RunOptions


def test_file_extraction_agent_route_calls_html_extractor(monkeypatch):
    from service.file_extraction_agent import processor as processor_module

    seen_call: dict[str, object] = {}

    def fake_extract(**kwargs):
        seen_call.update(kwargs)
        return ExtractionResult(
            result={"title": "通知"},
            trace={"actions": []},
        )

    monkeypatch.setattr(processor_module, "extract", fake_extract)

    client = TestClient(create_app())
    response = client.post(
        "/v1/file-extraction-agent/extract",
        json={
            "html": '<p id="dp-p-1">通知</p>',
            "task_spec": {
                "fields": [
                    {"name": "title", "type": "string", "required": True}
                ]
            },
        },
    )

    assert response.status_code == 200
    assert seen_call["html"] == '<p id="dp-p-1">通知</p>'
    assert seen_call["task_spec"].fields[0].name == "title"
    assert response.json()["result"]["title"] == "通知"


def test_file_extraction_agent_route_passes_run_options(monkeypatch):
    from service.file_extraction_agent import processor as processor_module

    seen_call: dict[str, object] = {}

    def fake_extract(**kwargs):
        seen_call.update(kwargs)
        return ExtractionResult()

    monkeypatch.setattr(processor_module, "extract", fake_extract)

    client = TestClient(create_app())
    response = client.post(
        "/v1/file-extraction-agent/extract",
        json={
            "html": '<p id="dp-p-1">通知</p>',
            "task_spec": {"fields": [{"name": "title"}]},
            "run_options": {"max_tool_calls": 33},
        },
    )

    assert response.status_code == 200
    assert seen_call["run_options"] == RunOptions(max_tool_calls=33)


def test_file_extraction_agent_route_passes_stage_model_overrides(monkeypatch):
    from service.file_extraction_agent import processor as processor_module

    seen_call: dict[str, object] = {}

    def fake_extract(**kwargs):
        seen_call.update(kwargs)
        return ExtractionResult()

    monkeypatch.setattr(processor_module, "extract", fake_extract)

    client = TestClient(create_app())
    response = client.post(
        "/v1/file-extraction-agent/extract",
        json={
            "html": '<p id="dp-p-1">通知</p>',
            "task_spec": {"fields": [{"name": "title"}]},
            "base_url": "https://example.com/v1",
            "openai_api_key": "key",
            "broad_model_name": "broad",
            "resolution_model_name": "resolution",
            "temperature": 0.2,
            "top_p": 0.9,
            "top_k": 40,
        },
    )

    assert response.status_code == 200
    config = seen_call["model_config"]
    assert config["base_url"] == "https://example.com/v1"
    assert config["api_key"] == "key"
    assert config["broad_model_name"] == "broad"
    assert config["resolution_model_name"] == "resolution"
    assert config["temperature"] == 0.2
    assert config["top_p"] == 0.9
    assert config["top_k"] == 40


def test_file_extraction_agent_route_accepts_model_config_object(monkeypatch):
    from service.file_extraction_agent import processor as processor_module

    seen_call: dict[str, object] = {}

    def fake_extract(**kwargs):
        seen_call.update(kwargs)
        return ExtractionResult()

    monkeypatch.setattr(processor_module, "extract", fake_extract)

    client = TestClient(create_app())
    response = client.post(
        "/v1/file-extraction-agent/extract",
        json={
            "html": '<p id="dp-p-1">通知</p>',
            "task_spec": {"fields": [{"name": "title"}]},
            "model_config": {
                "base_url": "https://example.com/v1",
                "api_key": "key",
                "broad_model_name": "broad",
                "resolution_model_name": "resolution",
            },
        },
    )

    assert response.status_code == 200
    assert seen_call["model_config"].broad_model_name == "broad"


def test_file_extraction_agent_route_returns_422_for_business_validation(monkeypatch):
    from service.file_extraction_agent import processor as processor_module

    def fake_extract(**kwargs):
        del kwargs
        raise ValueError("html must be a non-empty string")

    monkeypatch.setattr(processor_module, "extract", fake_extract)

    client = TestClient(create_app())
    response = client.post(
        "/v1/file-extraction-agent/extract",
        json={
            "html": " ",
            "task_spec": {"fields": [{"name": "title"}]},
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "html must be a non-empty string"


def test_file_extraction_agent_route_rejects_unknown_payload_fields():
    client = TestClient(create_app())
    response = client.post(
        "/v1/file-extraction-agent/extract",
        json={
            "html": '<p id="dp-p-1">通知</p>',
            "task_spec": {"fields": [{"name": "title"}]},
            "blocks": [],
        },
    )

    assert response.status_code == 422
