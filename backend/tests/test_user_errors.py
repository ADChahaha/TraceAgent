"""验证 backend HTTP 与轮次执行对外错误均脱敏为可操作英文提示，且服务端日志保留原始细节。"""

from __future__ import annotations

import json
import logging

from fastapi.testclient import TestClient
import pytest

from backend.core.config import BackendSettings
from backend.main import create_app
from backend.services.errors import AgentServiceError, DocumentServiceError
from backend.tests.test_session_manager import FakeAgent, FakeCall

FORBIDDEN_INTERNAL_TOKENS = ("gRPC", "ipv4:", "127.0.0.1", "8002", "socksio", "httpx", "Traceback", "pydantic")


def _sse_payloads(response) -> list[dict]:
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


class FailingUploadAgent(FakeAgent):
    def __init__(self, exc: Exception):
        super().__init__()
        self._exc = exc

    async def prepare_resources(self, *, session_id, files, remove_raw=None):
        raise self._exc


class FailingStreamCall(FakeCall):
    def __init__(self, exc: Exception):
        super().__init__()
        self._exc = exc

    async def __anext__(self):
        raise self._exc


class FailingChatAgent(FakeAgent):
    def __init__(self, exc: Exception | None = None, events: list[dict] | None = None):
        super().__init__()
        self._exc = exc
        self._events = list(events or [])

    def chat_completion(self, **request):
        if self._exc is not None:
            return FailingStreamCall(self._exc)
        call = super().chat_completion(**request)
        for event in self._events:
            call.events.put_nowait(event)
        call.events.put_nowait(None)
        return call


@pytest.mark.parametrize(
    ("raw_error", "expected_detail"),
    [
        (
            "document service gRPC: UNAVAILABLE: failed to connect to all addresses; last error: UNKNOWN: ipv4:127.0.0.1:8002: Connection refused",
            "Document processing is temporarily unavailable. Please try again in a moment.",
        ),
        (
            "document service gRPC: DEADLINE_EXCEEDED: Deadline Exceeded",
            "Document processing timed out. Try a smaller file or retry.",
        ),
        (
            "document service gRPC: INVALID_ARGUMENT: corrupted pdf stream",
            "This document could not be read. Check that the file is a valid PDF or DOCX and try again.",
        ),
        (
            "document service gRPC: INTERNAL: Traceback RuntimeError in parser",
            "We couldn't process this document right now. Please try again.",
        ),
    ],
)
def test_upload_http_errors_hide_internal_details_and_log_raw_error(tmp_path, caplog, raw_error, expected_detail):
    agent = FailingUploadAgent(DocumentServiceError(raw_error))
    app = create_app(settings=BackendSettings(database_path=tmp_path / "upload-err.sqlite3"), agent_client=agent)
    with caplog.at_level(logging.WARNING):
        with TestClient(app) as client:
            session_id = client.post("/chat/sessions").json()["session_id"]
            response = client.post(
                f"/chat/sessions/{session_id}/files",
                files=[("files", ("sample.pdf", b"%PDF-1.4", "application/pdf"))],
            )

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail == expected_detail
    for token in FORBIDDEN_INTERNAL_TOKENS:
        assert token.lower() not in detail.lower()
    assert raw_error in caplog.text


def test_http_validation_and_not_found_return_clear_english_messages(tmp_path):
    agent = FakeAgent()
    app = create_app(settings=BackendSettings(database_path=tmp_path / "validation-err.sqlite3"), agent_client=agent)
    with TestClient(app) as client:
        session_id = client.post("/chat/sessions").json()["session_id"]

        bad_type = client.post(
            f"/chat/sessions/{session_id}/files",
            files=[("files", ("notes.txt", b"hello", "text/plain"))],
        )
        assert bad_type.status_code == 422
        assert bad_type.json()["detail"] == "Only PDF and DOCX files are supported."

        bad_json = client.post("/chat/completion", json={"content": ""})
        assert bad_json.status_code == 422
        assert bad_json.json()["detail"] == "Invalid request body. Check your input and try again."

        missing = client.get("/resume", params={"session_id": "nonexistent"})
        assert missing.status_code == 404
        assert missing.json()["detail"] == "This workspace could not be found."


@pytest.mark.parametrize(
    ("agent", "expected_error", "expected_log"),
    [
        (
            FailingChatAgent(
                exc=AgentServiceError(
                    "agent gRPC: INTERNAL: completion initialization failed: Using SOCKS proxy, "
                    "but the 'socksio' package is not installed. Make sure to install httpx using `pip install httpx[socks]`."
                )
            ),
            "Unable to generate a response right now. Please try again.",
            "socksio",
        ),
        (
            FailingChatAgent(
                exc=AgentServiceError("agent gRPC: UNAVAILABLE: ipv4:127.0.0.1:8001: Connection refused")
            ),
            "The assistant service is temporarily unavailable. Please try again in a moment.",
            "UNAVAILABLE",
        ),
        (
            FailingChatAgent(
                events=[{"type": "completion.failed", "seq": 1, "error_message": "Error code: 429 - rate limit exceeded"}]
            ),
            "The assistant is busy right now. Please wait a moment and try again.",
            "429",
        ),
        (
            FailingChatAgent(
                events=[{"type": "completion.failed", "seq": 1, "error_message": "upstream request timed out after 30s"}]
            ),
            "The request timed out before an answer was ready. Please try again.",
            "timed out",
        ),
        (
            FailingChatAgent(events=[]),
            "The response stream was interrupted before completion. Please try again.",
            "without terminal event",
        ),
    ],
)
def test_turn_failure_sanitizes_sse_and_snapshot_while_logging_details(tmp_path, caplog, agent, expected_error, expected_log):
    app = create_app(settings=BackendSettings(database_path=tmp_path / "turn-err.sqlite3"), agent_client=agent)
    with caplog.at_level(logging.WARNING):
        with TestClient(app) as client:
            session_id = client.post("/chat/sessions").json()["session_id"]
            response = client.post("/chat/completion", json={"session_id": session_id, "content": "Summarize"})
            assert response.status_code == 200
            frames = _sse_payloads(response)
            failed_events = [frame for frame in frames if frame.get("type") == "turn.failed"]
            if failed_events:
                reported_error = failed_events[0]["payload"]["error"]
            else:
                # 轮次在首帧快照编码前已快速失败，终态直接落在首帧 session.snapshot 中。
                reported_error = frames[0]["state"]["turns"][0]["error"]
            assert reported_error == expected_error
            for token in FORBIDDEN_INTERNAL_TOKENS:
                assert token.lower() not in reported_error.lower()

            resumed = client.get("/resume", params={"session_id": session_id})
            snapshot = _sse_payloads(resumed)[0]
            assert snapshot["state"]["turns"][0]["status"] == "failed"
            assert snapshot["state"]["turns"][0]["error"] == expected_error

    assert expected_log in caplog.text
