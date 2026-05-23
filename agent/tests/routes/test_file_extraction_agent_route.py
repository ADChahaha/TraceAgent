from __future__ import annotations

from fastapi.testclient import TestClient

from main import create_app
from service.file_extraction_agent.schemas import RunOptions


def test_document_qa_chat_completion_route_calls_completion_stream(monkeypatch):
    from service.file_extraction_agent import processor as processor_module

    seen_call: dict[str, object] = {}

    def fake_create_completion_stream(**kwargs):
        seen_call.update(kwargs)
        yield 'event: completion.created\ndata: {"id":"cmp_123"}\n\n'
        yield 'event: completion.completed\ndata: {"id":"cmp_123"}\n\n'

    monkeypatch.setattr(processor_module, "create_completion_stream", fake_create_completion_stream)

    client = TestClient(create_app())
    with client.stream(
        "POST",
        "/v1/document-qa/chat/completions",
        json={
            "completion_id": "cmp_123",
            "documents": [{"filename": "notice.html", "html": '<p id="p1">通知</p>'}],
            "messages": [{"role": "user", "content": "这份文件说了什么？"}],
            "memory": {"prior_answers": ["上一轮摘要"]},
            "stream": True,
        },
    ) as response:
        body = response.read().decode()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert seen_call["completion_id"] == "cmp_123"
    assert seen_call["documents"][0].filename == "notice.html"
    assert seen_call["messages"][0].content == "这份文件说了什么？"
    assert seen_call["memory"].prior_answers == ["上一轮摘要"]
    assert body == (
        'event: completion.created\ndata: {"id":"cmp_123"}\n\n'
        'event: completion.completed\ndata: {"id":"cmp_123"}\n\n'
    )


def test_document_qa_chat_completion_route_passes_run_options(monkeypatch):
    from service.file_extraction_agent import processor as processor_module

    seen_call: dict[str, object] = {}

    def fake_create_completion_stream(**kwargs):
        seen_call.update(kwargs)
        yield 'event: completion.completed\ndata: {}\n\n'

    monkeypatch.setattr(processor_module, "create_completion_stream", fake_create_completion_stream)

    client = TestClient(create_app())
    response = client.post(
        "/v1/document-qa/chat/completions",
        json={
            "completion_id": "cmp_123",
            "documents": [{"filename": "notice.html", "html": '<p id="p1">通知</p>'}],
            "messages": [{"role": "user", "content": "问题"}],
            "run_options": {"max_tool_calls": 33},
        },
    )

    assert response.status_code == 200
    assert seen_call["run_options"] == RunOptions(max_tool_calls=33)


def test_document_qa_chat_completion_route_passes_model_overrides(monkeypatch):
    from service.file_extraction_agent import processor as processor_module

    seen_call: dict[str, object] = {}

    def fake_create_completion_stream(**kwargs):
        seen_call.update(kwargs)
        yield 'event: completion.completed\ndata: {}\n\n'

    monkeypatch.setattr(processor_module, "create_completion_stream", fake_create_completion_stream)

    client = TestClient(create_app())
    response = client.post(
        "/v1/document-qa/chat/completions",
        json={
            "completion_id": "cmp_123",
            "documents": [{"filename": "notice.html", "html": '<p id="p1">通知</p>'}],
            "messages": [{"role": "user", "content": "问题"}],
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


def test_document_qa_completion_cancel_route_calls_processor(monkeypatch):
    from service.file_extraction_agent import processor as processor_module

    seen_call: dict[str, object] = {}

    def fake_cancel_completion(completion_id):
        seen_call["completion_id"] = completion_id
        return {"id": completion_id, "status": "cancelling"}

    monkeypatch.setattr(processor_module, "cancel_completion", fake_cancel_completion)

    client = TestClient(create_app())
    response = client.post("/v1/document-qa/chat/completions/cmp_123/cancel")

    assert response.status_code == 200
    assert response.json() == {"id": "cmp_123", "status": "cancelling"}
    assert seen_call["completion_id"] == "cmp_123"


def test_legacy_file_extraction_route_is_removed():
    client = TestClient(create_app())
    response = client.post(
        "/v1/file-extraction-agent/extract/stream",
        json={
            "documents": [{"filename": "notice.html", "html": '<p id="p1">通知</p>'}],
            "task_spec": {"fields": [{"name": "title"}]},
        },
    )

    assert response.status_code == 404


def test_document_qa_chat_completion_rejects_task_spec_payload():
    client = TestClient(create_app())
    response = client.post(
        "/v1/document-qa/chat/completions",
        json={
            "completion_id": "cmp_123",
            "documents": [{"filename": "notice.html", "html": '<p id="p1">通知</p>'}],
            "messages": [{"role": "user", "content": "问题"}],
            "task_spec": {"fields": [{"name": "title"}]},
        },
    )

    assert response.status_code == 422


def test_document_qa_chat_completion_rejects_empty_documents_before_streaming():
    client = TestClient(create_app())
    response = client.post(
        "/v1/document-qa/chat/completions",
        json={
            "completion_id": "cmp_123",
            "documents": [],
            "messages": [{"role": "user", "content": "问题"}],
        },
    )

    assert response.status_code == 422
    assert "documents" in response.text
