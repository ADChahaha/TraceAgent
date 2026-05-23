from __future__ import annotations

from typing import Any

import pytest

from backend.services.agent_client import AgentClient


def test_process_document_routes_pdf_to_existing_pdf_endpoint(monkeypatch):
    client = AgentClient(base_url="http://agent.local")
    seen_call: dict[str, Any] = {}

    def fake_post(path: str, **kwargs):
        seen_call["path"] = path
        seen_call["kwargs"] = kwargs
        return {"filename": "sample.pdf", "html": "<p>pdf</p>"}

    monkeypatch.setattr(client, "_post", fake_post)

    result = client.process_document(
        file_bytes=b"%PDF-1.4",
        filename="sample.pdf",
        content_type="application/pdf",
        file_type="pdf",
    )

    assert result == {"filename": "sample.pdf", "html": "<p>pdf</p>"}
    assert seen_call["path"] == "/v1/document-processor/process"
    assert seen_call["kwargs"]["data"] == {"file_type": "pdf"}
    assert seen_call["kwargs"]["files"]["file"] == (
        "sample.pdf",
        b"%PDF-1.4",
        "application/pdf",
    )


def test_process_document_routes_docx_to_docx_endpoint(monkeypatch):
    client = AgentClient(base_url="http://agent.local")
    seen_call: dict[str, Any] = {}

    def fake_post(path: str, **kwargs):
        seen_call["path"] = path
        seen_call["kwargs"] = kwargs
        return {"filename": "sample.docx", "html": "<p>docx</p>"}

    monkeypatch.setattr(client, "_post", fake_post)

    result = client.process_document(
        file_bytes=b"PK\x03\x04",
        filename="sample.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_type="docx",
    )

    assert result == {"filename": "sample.docx", "html": "<p>docx</p>"}
    assert seen_call["path"] == "/v1/document-processor/docx/process"
    assert seen_call["kwargs"]["data"] == {"file_type": "docx"}
    assert seen_call["kwargs"]["files"]["file"] == (
        "sample.docx",
        b"PK\x03\x04",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


def test_process_document_rejects_unknown_file_type_before_agent_call(monkeypatch):
    client = AgentClient(base_url="http://agent.local")
    called = False

    def fake_post(*args, **kwargs):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(client, "_post", fake_post)

    with pytest.raises(ValueError, match="Unsupported file type"):
        client.process_document(
            file_bytes=b"hello",
            filename="sample.txt",
            content_type="text/plain",
            file_type="txt",
        )

    assert called is False
