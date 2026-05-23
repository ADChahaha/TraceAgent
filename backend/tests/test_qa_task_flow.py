from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from backend.core.config import BackendSettings
from backend.main import create_app
from backend.services.errors import ConflictError
from backend.services.time_utils import utc_now


class FakeQaAgentClient:
    def __init__(self):
        self.document_calls: list[dict[str, Any]] = []
        self.completion_calls: list[dict[str, Any]] = []
        self.cancel_calls: list[str] = []

    def process_document(
        self,
        *,
        file_bytes: bytes,
        filename: str,
        content_type: str | None,
        file_type: str,
    ) -> dict[str, Any]:
        self.document_calls.append(
            {
                "file_bytes": file_bytes,
                "filename": filename,
                "content_type": content_type,
                "file_type": file_type,
            }
        )
        return {
            "filename": filename,
            "html": '<h1 id="h1">合同</h1><p id="p1">Either party may terminate with 30 days notice.</p>',
            "display_html": '<html><body><p id="p1">Either party may terminate with 30 days notice.</p></body></html>',
            "markdown": "Either party may terminate with 30 days notice.",
            "md_list": ["Either party may terminate with 30 days notice."],
            "blocks": [
                {
                    "text": "Either party may terminate with 30 days notice.",
                    "kind": "text",
                    "page_no": 1,
                    "meta_info": {},
                }
            ],
            "meta_info": {"processor": "fake"},
            "warnings": [],
        }

    def create_document_qa_completion_stream(
        self,
        *,
        completion_id: str,
        documents: list[dict[str, Any]],
        messages: list[dict[str, str]],
        memory: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        run_options: dict[str, Any] | None = None,
    ):
        self.completion_calls.append(
            {
                "completion_id": completion_id,
                "documents": documents,
                "messages": messages,
                "memory": memory,
                "metadata": metadata,
                "run_options": run_options,
            }
        )
        yield {
            "id": completion_id,
            "type": "completion.created",
            "status": "in_progress",
        }
        yield {
            "type": "source_indexed",
            "result": {
                "ok": True,
                "document_tree": "evidence://0001 contract.pdf",
                "source_selectors": {"0001.0001.0001": "p1"},
            },
        }
        yield {
            "type": "model_message",
            "tool_call_count": 1,
            "tool_calls": [
                {
                    "id": "call_read_notice",
                    "name": "read",
                    "args": {"locator": "evidence://0001.0001.0001"},
                }
            ],
            "content": "可以提前终止，但需要提前 30 天通知。[30 天通知](evidence://0001.0001.0001/S001)",
        }
        yield {
            "type": "tool_completed",
            "tool": "read",
            "args": {"locator": "evidence://0001.0001.0001"},
            "result": {
                "ok": True,
                "locator": "evidence://0001.0001.0001",
                "kind": "paragraph",
                "text": "Either party may terminate with 30 days notice.",
            },
        }
        yield {
            "type": "model_message",
            "content": "最终答案：可以提前终止，但要提前 30 天通知。[30 天通知](evidence://0001.0001.0001/S001)",
        }
        yield {
            "id": completion_id,
            "type": "completion.completed",
            "status": "completed",
        }

    def cancel_document_qa_completion(self, completion_id: str) -> dict[str, Any]:
        self.cancel_calls.append(completion_id)
        return {"id": completion_id, "status": "cancelling"}


class BlockingCancelQaAgentClient(FakeQaAgentClient):
    def __init__(self):
        super().__init__()
        self.cancel_started = threading.Event()
        self.cancel_release = threading.Event()

    def cancel_document_qa_completion(self, completion_id: str) -> dict[str, Any]:
        self.cancel_calls.append(completion_id)
        self.cancel_started.set()
        self.cancel_release.wait(timeout=1.0)
        return {"id": completion_id, "status": "cancelling"}


class LateCompletionQaAgentClient(FakeQaAgentClient):
    def __init__(self):
        super().__init__()
        self.stream_started = threading.Event()
        self.release_stream = threading.Event()

    def create_document_qa_completion_stream(
        self,
        *,
        completion_id: str,
        documents: list[dict[str, Any]],
        messages: list[dict[str, str]],
        memory: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        run_options: dict[str, Any] | None = None,
    ):
        self.completion_calls.append(
            {
                "completion_id": completion_id,
                "documents": documents,
                "messages": messages,
                "memory": memory,
                "metadata": metadata,
                "run_options": run_options,
            }
        )
        yield {
            "id": completion_id,
            "type": "completion.created",
            "status": "in_progress",
        }
        self.stream_started.set()
        self.release_stream.wait(timeout=1.0)
        yield {
            "type": "model_message",
            "content": "迟到答案不应该入库。",
        }
        yield {
            "id": completion_id,
            "type": "completion.completed",
            "status": "completed",
        }


class TerminalRaceQaAgentClient(FakeQaAgentClient):
    def create_document_qa_completion_stream(
        self,
        *,
        completion_id: str,
        documents: list[dict[str, Any]],
        messages: list[dict[str, str]],
        memory: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        run_options: dict[str, Any] | None = None,
    ):
        self.completion_calls.append(
            {
                "completion_id": completion_id,
                "documents": documents,
                "messages": messages,
                "memory": memory,
                "metadata": metadata,
                "run_options": run_options,
            }
        )
        yield {
            "type": "model_message",
            "content": "最终答案已经提交。",
        }
        yield {
            "id": completion_id,
            "type": "completion.completed",
            "status": "completed",
        }


def build_app(tmp_path: Path, agent_client: FakeQaAgentClient | None = None):
    fake_agent = agent_client or FakeQaAgentClient()
    app = create_app(
        settings=BackendSettings(database_path=tmp_path / "backend.sqlite3"),
        agent_client=fake_agent,
    )
    return app, fake_agent


def create_qa_task(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/qa/tasks",
        data={"metadata": json.dumps({"workspace": "demo"}, ensure_ascii=False)},
        files={"files": ("contract.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert response.status_code == 200
    return response.json()


def create_docx_qa_task(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/qa/tasks",
        data={"metadata": json.dumps({"workspace": "demo"}, ensure_ascii=False)},
        files={
            "files": (
                "contract.docx",
                b"PK\x03\x04 fake docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert response.status_code == 200
    return response.json()


def sse_events(response_text: str) -> list[dict[str, Any]]:
    lines = [
        line.removeprefix("data: ")
        for line in response_text.splitlines()
        if line.startswith("data: ")
    ]
    return [json.loads(line) for line in lines]


def wait_for_task_status(client: TestClient, task_id: str, status: str, *, timeout_seconds: float = 2.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_summary: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        response = client.get(f"/qa/tasks/{task_id}")
        assert response.status_code == 200
        last_summary = response.json()
        if last_summary["status"] == status:
            return last_summary
        time.sleep(0.02)
    raise AssertionError(f"task {task_id} did not reach {status}; last summary={last_summary}")


def wait_until(condition, *, timeout_seconds: float = 1.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.02)
    raise AssertionError("condition was not met before timeout")


def test_create_qa_task_processes_documents_without_task_spec(tmp_path: Path):
    app, fake_agent = build_app(tmp_path)

    with TestClient(app) as client:
        created = create_qa_task(client)
        ready_summary = wait_for_task_status(client, created["task_id"], "ready")
        summary_response = client.get(f"/qa/tasks/{created['task_id']}")
        list_response = client.get("/qa/tasks")
        old_route_response = client.post("/tasks")

    assert created["status"] == "processing"
    assert created["stage"] == "document_processing"
    assert created["document_count"] == 0
    assert ready_summary["status"] == "ready"
    assert ready_summary["stage"] == "ready"
    assert ready_summary["document_count"] == 1
    assert ready_summary["stream"]["last_event_seq"] >= 2
    assert fake_agent.document_calls[0]["filename"] == "contract.pdf"
    assert summary_response.status_code == 200
    assert summary_response.json()["document_count"] == 1
    assert list_response.json()["tasks"][0]["task_id"] == created["task_id"]
    assert old_route_response.status_code == 404


def test_create_qa_task_accepts_docx_and_forwards_docx_type(tmp_path: Path):
    app, fake_agent = build_app(tmp_path)

    with TestClient(app) as client:
        created = create_docx_qa_task(client)
        ready_summary = wait_for_task_status(client, created["task_id"], "ready")
        detail_response = client.get(f"/qa/tasks/{created['task_id']}")

    assert created["status"] == "processing"
    assert ready_summary["document_count"] == 1
    assert fake_agent.document_calls[0]["filename"] == "contract.docx"
    assert fake_agent.document_calls[0]["file_type"] == "docx"
    assert fake_agent.document_calls[0]["content_type"] == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert detail_response.status_code == 200
    assert detail_response.json()["documents"][0]["filename"] == "contract.docx"


def test_qa_input_runs_agent_completion_and_persists_events(tmp_path: Path):
    app, fake_agent = build_app(tmp_path)

    with TestClient(app) as client:
        task = create_qa_task(client)
        wait_for_task_status(client, task["task_id"], "ready")
        input_response = client.post(
            f"/qa/tasks/{task['task_id']}/inputs",
            json={"content": "这份合同可以提前终止吗？"},
        )
        completed_summary = wait_for_task_status(client, task["task_id"], "ready")
        detail_response = client.get(f"/qa/tasks/{task['task_id']}")
        events_response = client.get(f"/qa/tasks/{task['task_id']}/events?after_seq=0")

    assert input_response.status_code == 200
    assert input_response.json()["status"] == "queued"
    assert completed_summary["stream"]["state"] == "idle"
    assert detail_response.status_code == 200
    assert detail_response.json()["documents"] == [
        {
            "document_id": detail_response.json()["documents"][0]["document_id"],
            "filename": "contract.pdf",
            "display_html": '<html><body><p id="p1">Either party may terminate with 30 days notice.</p></body></html>',
        }
    ]
    assert detail_response.json()["source_selectors"] == {"0001.0001.0001": "p1"}
    assert fake_agent.completion_calls[0]["documents"] == [
        {
            "filename": "contract.pdf",
            "html": '<h1 id="h1">合同</h1><p id="p1">Either party may terminate with 30 days notice.</p>',
        }
    ]
    assert fake_agent.completion_calls[0]["messages"] == [
        {"role": "user", "content": "这份合同可以提前终止吗？"}
    ]

    events = sse_events(events_response.text)
    event_types = [event["type"] for event in events]
    assert events_response.status_code == 200
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    assert "message.created" in event_types
    assert "turn.created" in event_types
    assert any(
        event["type"] == "agent.event"
        and event["payload"]["type"] == "model_message"
        and "evidence://0001.0001.0001/S001" in event["payload"]["content"]
        for event in events
    )
    assert events[-1]["type"] == "turn.completed"


def test_qa_second_input_sends_prior_messages_to_agent(tmp_path: Path):
    app, fake_agent = build_app(tmp_path)

    with TestClient(app) as client:
        task = create_qa_task(client)
        wait_for_task_status(client, task["task_id"], "ready")
        first = client.post(
            f"/qa/tasks/{task['task_id']}/inputs",
            json={"content": "可以提前终止吗？"},
        )
        wait_for_task_status(client, task["task_id"], "ready")
        second = client.post(
            f"/qa/tasks/{task['task_id']}/inputs",
            json={"content": "通知期限是多少？"},
        )
        wait_for_task_status(client, task["task_id"], "ready")

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(fake_agent.completion_calls) == 2
    assert fake_agent.completion_calls[1]["messages"] == [
        {"role": "user", "content": "可以提前终止吗？"},
        {
            "role": "assistant",
            "content": "可以提前终止，但需要提前 30 天通知。[30 天通知](evidence://0001.0001.0001/S001)",
            "tool_calls": [
                {
                    "id": "call_read_notice",
                    "type": "function",
                    "function": {
                        "name": "read",
                        "arguments": json.dumps({"locator": "evidence://0001.0001.0001"}, ensure_ascii=False),
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_read_notice",
            "name": "read",
            "content": json.dumps(
                {
                    "ok": True,
                    "locator": "evidence://0001.0001.0001",
                    "kind": "paragraph",
                    "text": "Either party may terminate with 30 days notice.",
                },
                ensure_ascii=False,
            ),
        },
        {
            "role": "assistant",
            "content": "最终答案：可以提前终止，但要提前 30 天通知。[30 天通知](evidence://0001.0001.0001/S001)",
        },
        {"role": "user", "content": "通知期限是多少？"},
    ]


def test_qa_task_rejects_new_input_while_turn_is_active(tmp_path: Path):
    app, _fake_agent = build_app(tmp_path)

    with TestClient(app) as client:
        task = create_qa_task(client)
        wait_for_task_status(client, task["task_id"], "ready")
        service = client.app.state.qa_task_service
        service.create_input(
            task_id=task["task_id"],
            content="先占用 active turn",
            run_agent=False,
        )
        response = client.post(
            f"/qa/tasks/{task['task_id']}/inputs",
            json={"content": "第二个问题"},
        )

    assert response.status_code == 409
    assert "active turn" in response.text


def test_qa_cancel_active_turn_calls_agent_cancel(tmp_path: Path):
    fake_agent = FakeQaAgentClient()
    app, _ = build_app(tmp_path, agent_client=fake_agent)

    with TestClient(app) as client:
        task = create_qa_task(client)
        wait_for_task_status(client, task["task_id"], "ready")
        service = client.app.state.qa_task_service
        turn = service.create_input(
            task_id=task["task_id"],
            content="准备取消的问题",
            run_agent=False,
        )
        now = utc_now()
        service.connection.execute(
            """
            UPDATE qa_turns
            SET status = ?, agent_completion_id = ?, updated_at = ?
            WHERE id = ?
            """,
            ("in_progress", "cmp_cancel", now, turn["turn_id"]),
        )
        service.connection.commit()

        response = client.post(f"/qa/tasks/{task['task_id']}/cancel")
        wait_until(lambda: fake_agent.cancel_calls == ["cmp_cancel"])
        events = service.list_task_events(task["task_id"], after_sequence=0)
        summary = client.get(f"/qa/tasks/{task['task_id']}").json()

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert fake_agent.cancel_calls == ["cmp_cancel"]
    assert any(event["type"] == "turn.cancel_requested" for event in events)
    assert any(event["type"] == "turn.cancelled" for event in events)
    assert summary["stream"]["state"] == "idle"


def test_qa_cancel_does_not_wait_for_agent_cancel_when_provider_is_stuck(tmp_path: Path):
    fake_agent = BlockingCancelQaAgentClient()
    app, _ = build_app(tmp_path, agent_client=fake_agent)

    with TestClient(app) as client:
        task = create_qa_task(client)
        wait_for_task_status(client, task["task_id"], "ready")
        service = client.app.state.qa_task_service
        turn = service.create_input(
            task_id=task["task_id"],
            content="准备取消的问题",
            run_agent=False,
        )
        now = utc_now()
        service.connection.execute(
            """
            UPDATE qa_turns
            SET status = ?, agent_completion_id = ?, updated_at = ?
            WHERE id = ?
            """,
            ("in_progress", "cmp_blocked_cancel", now, turn["turn_id"]),
        )
        service.connection.commit()

        started_at = time.monotonic()
        try:
            response = client.post(f"/qa/tasks/{task['task_id']}/cancel")
            elapsed = time.monotonic() - started_at
            assert fake_agent.cancel_started.wait(timeout=0.5)
        finally:
            fake_agent.cancel_release.set()
        events = service.list_task_events(task["task_id"], after_sequence=0)
        summary = client.get(f"/qa/tasks/{task['task_id']}").json()

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert elapsed < 0.25
    assert fake_agent.cancel_calls == ["cmp_blocked_cancel"]
    assert any(event["type"] == "turn.cancel_requested" for event in events)
    assert any(event["type"] == "turn.cancelled" for event in events)
    assert summary["stream"]["state"] == "idle"


def test_qa_cancelled_turn_ignores_late_agent_completion(tmp_path: Path):
    fake_agent = LateCompletionQaAgentClient()
    app, _ = build_app(tmp_path, agent_client=fake_agent)

    with TestClient(app) as client:
        task = create_qa_task(client)
        wait_for_task_status(client, task["task_id"], "ready")
        input_response = client.post(
            f"/qa/tasks/{task['task_id']}/inputs",
            json={"content": "准备取消的问题"},
        )
        assert input_response.status_code == 200
        assert fake_agent.stream_started.wait(timeout=1.0)
        service = client.app.state.qa_task_service

        cancel_response = client.post(f"/qa/tasks/{task['task_id']}/cancel")
        cancelled_summary = wait_for_task_status(client, task["task_id"], "ready")
        fake_agent.release_stream.set()
        time.sleep(0.1)
        events = service.list_task_events(task["task_id"], after_sequence=0)
        detail = client.get(f"/qa/tasks/{task['task_id']}").json()

    event_types = [event["type"] for event in events]
    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "cancelled"
    assert cancelled_summary["stream"]["state"] == "idle"
    assert "turn.cancelled" in event_types
    assert "turn.completed" not in event_types
    assert all(
        not (
            event["type"] == "agent.event"
            and event["payload"].get("type") == "model_message"
            and event["payload"].get("content") == "迟到答案不应该入库。"
        )
        for event in events
    )
    assert detail["stream"]["state"] == "idle"


def test_qa_completed_terminal_event_wins_over_racing_cancel(tmp_path: Path):
    fake_agent = TerminalRaceQaAgentClient()
    app, _ = build_app(tmp_path, agent_client=fake_agent)

    with TestClient(app) as client:
        task = create_qa_task(client)
        wait_for_task_status(client, task["task_id"], "ready")
        service = client.app.state.qa_task_service
        original_emit_agent_event = service._emit_agent_event
        terminal_event_committed = threading.Event()
        release_terminal_commit = threading.Event()

        def paused_emit_agent_event(*, task_id: str, turn_id: str, event: dict[str, Any]) -> None:
            original_emit_agent_event(task_id=task_id, turn_id=turn_id, event=event)
            if event.get("type") == "completion.completed":
                terminal_event_committed.set()
                release_terminal_commit.wait(timeout=1.0)

        service._emit_agent_event = paused_emit_agent_event
        input_response = client.post(
            f"/qa/tasks/{task['task_id']}/inputs",
            json={"content": "准备和完成竞争的问题"},
        )
        assert input_response.status_code == 200
        assert terminal_event_committed.wait(timeout=1.0)

        cancel_result: dict[str, Any] = {}
        cancel_done = threading.Event()

        def cancel_task() -> None:
            try:
                cancel_result["value"] = service.cancel_task(task["task_id"])
            except Exception as exc:
                cancel_result["error"] = exc
            finally:
                cancel_done.set()

        cancel_thread = threading.Thread(target=cancel_task, daemon=True)
        cancel_thread.start()
        try:
            time.sleep(0.05)
            assert not cancel_done.is_set()
        finally:
            release_terminal_commit.set()
            cancel_thread.join(timeout=1.0)

        completed_summary = wait_for_task_status(client, task["task_id"], "ready")
        events = service.list_task_events(task["task_id"], after_sequence=0)

    event_types = [event["type"] for event in events]
    assert completed_summary["stream"]["state"] == "idle"
    assert isinstance(cancel_result.get("error"), ConflictError)
    assert "turn.completed" in event_types
    assert "turn.cancelled" not in event_types
