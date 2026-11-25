"""会话标题旧库迁移、异步并发生成、失败/超时降级与旧会话兜底派生测试。"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path

from fastapi.testclient import TestClient

from backend.core.config import BackendSettings
from backend.core.db import connect_database, initialize_database
from backend.crud import crud
from backend.main import create_app
from backend.tests.test_qa_task_flow import AutoAgent, payloads


class TitleAgent(AutoAgent):
    def __init__(self, *, title_result="Lease Payment Schedule", delay: float = 0.0, fail: bool = False):
        super().__init__()
        self.title_result = title_result
        self.delay = delay
        self.fail = fail
        self.title_calls: list[dict] = []

    async def generate_title(self, *, question: str, filenames=None, timeout_seconds: float = 15.0) -> str:
        self.title_calls.append({"question": question, "filenames": list(filenames or ())})
        if self.delay > 0:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("title provider down")
        return self.title_result


def _wait_for_persisted_title(db_path: Path, session_id: str, timeout: float = 3.0) -> str | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        conn = connect_database(db_path)
        try:
            row = crud.get_session(conn, session_id)
            if row and row.get("title"):
                return row["title"]
        finally:
            conn.close()
        time.sleep(0.02)
    return None


def test_initialize_database_migrates_legacy_chat_sessions_without_title_column(tmp_path: Path):
    db_path = tmp_path / "legacy.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE chat_sessions (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            active_turn_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        INSERT INTO chat_sessions (id, status, active_turn_id, created_at, updated_at)
        VALUES ('legacy-uuid-1234', 'ready', NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
        """
    )
    conn.commit()

    initialize_database(conn)
    initialize_database(conn)  # 幂等再次执行

    columns = {row["name"] for row in conn.execute("PRAGMA table_info(chat_sessions)").fetchall()}
    assert "title" in columns
    row = crud.get_session(conn, "legacy-uuid-1234")
    assert row is not None and row["title"] is None
    conn.close()


def test_first_turn_generates_title_async_and_second_turn_does_not_overwrite(tmp_path: Path):
    db_path = tmp_path / "titles.sqlite3"
    agent = TitleAgent(title_result="Quarterly Revenue Breakdown")
    settings = BackendSettings(database_path=db_path)

    with TestClient(create_app(settings=settings, agent_client=agent)) as client:
        session_id = client.post("/chat/sessions").json()["session_id"]
        upload = client.post(
            f"/chat/sessions/{session_id}/files",
            files=[("files", ("q3-report.pdf", b"%PDF-1.4 sample", "application/pdf"))],
        )
        assert upload.status_code == 200

        # 提问前目录已回退显示文件名，而不是 UUID
        before = client.get("/chat/sessions").json()["sessions"]
        assert before[0]["id"] == session_id
        assert before[0]["title"] == "q3-report.pdf"

        stream = client.post(
            "/chat/completion",
            json={"session_id": session_id, "content": "Break down Q3 revenue by segment"},
        )
        assert stream.status_code == 200
        frames = payloads(stream)
        assert frames[-1]["type"] == "turn.completed"

        persisted = _wait_for_persisted_title(db_path, session_id)
        assert persisted == "Quarterly Revenue Breakdown"
        assert len(agent.title_calls) == 1
        assert agent.title_calls[0]["filenames"] == ["q3-report.pdf"]

        listed = client.get("/chat/sessions").json()["sessions"]
        assert listed[0]["title"] == "Quarterly Revenue Breakdown"

        resumed = payloads(client.get("/resume", params={"session_id": session_id}))
        assert resumed[0]["state"]["title"] == "Quarterly Revenue Breakdown"

        # 第二轮不再重复触发标题生成
        second = client.post("/chat/completion", json={"session_id": session_id, "content": "What about Q4?"})
        assert second.status_code == 200
        assert payloads(second)[-1]["type"] == "turn.completed"
        assert len(agent.title_calls) == 1


def test_title_failure_and_timeout_do_not_block_completion_and_fall_back_safely(tmp_path: Path):
    for name, agent, timeout_sec in (
        ("error", TitleAgent(fail=True), 5.0),
        ("timeout", TitleAgent(delay=1.0), 0.05),
    ):
        db_path = tmp_path / f"{name}.sqlite3"
        settings = BackendSettings(database_path=db_path, title_generation_timeout_seconds=timeout_sec)
        with TestClient(create_app(settings=settings, agent_client=agent)) as client:
            session_id = client.post("/chat/sessions").json()["session_id"]
            stream = client.post(
                "/chat/completion",
                json={"session_id": session_id, "content": "Explain the termination clause in section 9"},
            )
            assert stream.status_code == 200
            frames = payloads(stream)
            assert frames[-1]["type"] == "turn.completed"

            persisted = _wait_for_persisted_title(db_path, session_id)
            assert persisted == "Explain the termination clause in section 9"


class SlowChatFastTitleAgent(TitleAgent):
    def chat_completion(self, **request):
        from backend.tests.test_session_manager import FakeAgent

        call = FakeAgent.chat_completion(self, **request)
        loop = asyncio.get_running_loop()

        def emit_done():
            call.events.put_nowait({"type": "model_message.delta", "seq": 1, "message_id": "m", "delta": "回"})
            call.events.put_nowait({"type": "model_message.done", "seq": 2, "message_id": "m", "content": "回答"})
            call.events.put_nowait({"type": "completion.completed", "seq": 3})

        loop.call_later(0.08, emit_done)
        return call


def test_sse_stream_emits_session_updated_with_generated_title(tmp_path: Path):
    db_path = tmp_path / "sse-title.sqlite3"
    agent = SlowChatFastTitleAgent(title_result="Vendor SLA Penalties")
    with TestClient(create_app(settings=BackendSettings(database_path=db_path), agent_client=agent)) as client:
        session_id = client.post("/chat/sessions").json()["session_id"]
        stream = client.post(
            "/chat/completion",
            json={"session_id": session_id, "content": "What are the vendor SLA penalties?"},
        )
        assert stream.status_code == 200
        frames = payloads(stream)
        updated_events = [item for item in frames if item.get("type") == "session.updated"]
        assert updated_events == [
            {"turn_id": None, "type": "session.updated", "payload": {"title": "Vendor SLA Penalties"}}
        ]
        assert frames[-1]["type"] == "turn.completed"


def test_legacy_sessions_without_title_derive_readable_fallbacks_never_uuid(tmp_path: Path):
    db_path = tmp_path / "fallback.sqlite3"
    conn = connect_database(db_path)
    initialize_database(conn)
    with crud.transaction(conn):
        crud.create_session(conn, session_id="s-empty", status="ready", now="2026-01-01T00:00:01Z")
        crud.create_session(conn, session_id="s-file", status="ready", now="2026-01-01T00:00:02Z")
        crud.create_resource(
            conn,
            resource_id="r1",
            session_id="s-file",
            resource_type="raw",
            location="s3://res_s-file/raw/service-agreement.docx",
            now="2026-01-01T00:00:02Z",
            size_bytes=100,
        )
        crud.create_session(conn, session_id="s-msg", status="ready", now="2026-01-01T00:00:03Z")
        crud.create_turn(conn, turn_id="t1", session_id="s-msg", status="completed", now="2026-01-01T00:00:03Z")
        crud.create_message(
            conn,
            message_id="m1",
            session_id="s-msg",
            turn_id="t1",
            role="user",
            content="Summarize the indemnity obligations.",
            now="2026-01-01T00:00:03Z",
            sequence=1,
            group_id="g1",
            group_index=0,
        )
    conn.close()

    with TestClient(create_app(settings=BackendSettings(database_path=db_path), agent_client=AutoAgent())) as client:
        rows = {row["id"]: row["title"] for row in client.get("/chat/sessions").json()["sessions"]}
        assert rows == {
            "s-empty": "Untitled workspace",
            "s-file": "service-agreement.docx",
            "s-msg": "Summarize the indemnity obligations",
        }
        for sid, expected_title in rows.items():
            snapshot = payloads(client.get("/resume", params={"session_id": sid}))[0]
            assert snapshot["state"]["title"] == expected_title


def test_clean_title_preserves_internal_quotes_and_refresh_state_keeps_persisted_title():
    from backend.services.session_title import clean_session_title
    from backend.services.session_manager import SessionManager

    assert clean_session_title("《采购合同》违约条款。") == "《采购合同》违约条款"
    assert clean_session_title('Review of "Section 9".') == 'Review of "Section 9"'
    assert clean_session_title('"Wrapped Title."') == "Wrapped Title"

    dummy = object.__new__(SessionManager)
    dummy.session = {"id": "s1", "title": "Persisted Model Title", "status": "ready"}
    merged = dummy._merge_session_state({"id": "s1", "title": None, "status": "ready"})
    assert merged["title"] == "Persisted Model Title"
