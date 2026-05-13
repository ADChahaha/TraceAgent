from __future__ import annotations

from fastapi.testclient import TestClient

from main import create_app
from service.file_extraction_agent.schemas import RunOptions


def test_file_extraction_agent_stream_route_calls_stream_extractor(monkeypatch):
    from service.file_extraction_agent import processor as processor_module

    seen_call: dict[str, object] = {}

    def fake_extract_stream(**kwargs):
        seen_call.update(kwargs)
        yield '{"type":"tool_started","seq":1}\n'
        yield '{"type":"result_completed","seq":2}\n'

    monkeypatch.setattr(processor_module, "extract_stream", fake_extract_stream)

    client = TestClient(create_app())
    with client.stream(
        "POST",
        "/v1/file-extraction-agent/extract/stream",
        json={
            "documents": [{"filename": "notice.html", "html": '<p id="p1">通知</p>'}],
            "task_spec": {
                "fields": [
                    {"name": "title", "type": "string", "required": True}
                ]
            },
        },
    ) as response:
        body = response.read().decode()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert seen_call["documents"][0].filename == "notice.html"
    assert seen_call["task_spec"].fields[0].name == "title"
    assert body == '{"type":"tool_started","seq":1}\n{"type":"result_completed","seq":2}\n'


def test_file_extraction_agent_stream_route_passes_run_options(monkeypatch):
    from service.file_extraction_agent import processor as processor_module

    seen_call: dict[str, object] = {}

    def fake_extract_stream(**kwargs):
        seen_call.update(kwargs)
        yield '{"type":"result_completed"}\n'

    monkeypatch.setattr(processor_module, "extract_stream", fake_extract_stream)

    client = TestClient(create_app())
    response = client.post(
        "/v1/file-extraction-agent/extract/stream",
        json={
            "documents": [{"filename": "notice.html", "html": '<p id="p1">通知</p>'}],
            "task_spec": {"fields": [{"name": "title"}]},
            "run_options": {"max_tool_calls": 33},
        },
    )

    assert response.status_code == 200
    assert seen_call["run_options"] == RunOptions(max_tool_calls=33)


def test_file_extraction_agent_stream_route_passes_resolution_model_overrides(monkeypatch):
    from service.file_extraction_agent import processor as processor_module

    seen_call: dict[str, object] = {}

    def fake_extract_stream(**kwargs):
        seen_call.update(kwargs)
        yield '{"type":"result_completed"}\n'

    monkeypatch.setattr(processor_module, "extract_stream", fake_extract_stream)

    client = TestClient(create_app())
    response = client.post(
        "/v1/file-extraction-agent/extract/stream",
        json={
            "documents": [{"filename": "notice.html", "html": '<p id="p1">通知</p>'}],
            "task_spec": {"fields": [{"name": "title"}]},
            "base_url": "https://example.com/v1",
            "openai_api_key": "key",
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
    assert config["resolution_model_name"] == "resolution"
    assert config["temperature"] == 0.2
    assert config["top_p"] == 0.9
    assert config["top_k"] == 40


def test_file_extraction_agent_stream_route_rejects_legacy_html_payload():
    client = TestClient(create_app())
    response = client.post(
        "/v1/file-extraction-agent/extract/stream",
        json={
            "html": '<p id="p1">通知</p>',
            "task_spec": {"fields": [{"name": "title"}]},
        },
    )

    assert response.status_code == 422


def test_file_extraction_agent_stream_route_rejects_unknown_payload_fields():
    client = TestClient(create_app())
    response = client.post(
        "/v1/file-extraction-agent/extract/stream",
        json={
            "documents": [{"filename": "notice.html", "html": '<p id="p1">通知</p>'}],
            "task_spec": {"fields": [{"name": "title"}]},
            "blocks": [],
        },
    )

    assert response.status_code == 422
