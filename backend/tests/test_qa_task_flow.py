"""completion/resume/cancel 与会话文件 API 的 HTTP 契约。"""

import asyncio
import json

from fastapi.testclient import TestClient

from backend.main import create_app
from backend.core.config import BackendSettings
from backend.tests.test_session_manager import FakeAgent, next_type


class AutoAgent(FakeAgent):
    def chat_completion(self, **request):
        call = super().chat_completion(**request)
        call.events.put_nowait({"type": "model_message.delta", "seq": 1, "message_id": "m", "delta": "回"})
        call.events.put_nowait({"type": "model_message.done", "seq": 2, "message_id": "m", "content": "回答"})
        call.events.put_nowait({"type": "completion.completed", "seq": 3})
        return call


def payloads(response):
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def test_completion_and_resume_return_snapshot_without_cursor(tmp_path):
    agent = AutoAgent()
    app = create_app(settings=BackendSettings(database_path=tmp_path / "api.sqlite3"), agent_client=agent)
    with TestClient(app) as client:
        session_id = client.post("/chat/sessions").json()["session_id"]
        response = client.post("/chat/completion", json={"content": "问题", "session_id": session_id})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        first = payloads(response)[0]
        assert first["session_id"] == session_id
        assert "id: " not in response.text
        resumed = client.get("/resume", params={"session_id": session_id})
        snapshot = payloads(resumed)[0]
        assert snapshot["state"]["turns"][0]["status"] == "completed"
        assert snapshot["state"]["turns"][0]["items"][-1]["text"] == "回答"
        assert len(agent.calls) == 1
        turn_id = snapshot["state"]["turns"][0]["id"]
        assert client.post("/cancel", json={"session_id": session_id, "turn_id": turn_id}).json()["status"] == "completed"
        assert client.get("/resume", params={"session_id": "missing"}).status_code == 404
        assert client.post("/chat/completion", json={"content": ""}).status_code == 422
        assert client.post("/chat/completion", json={"content": "问题"}).status_code == 422
        assert client.post("/chat/completion", json={"content": "问题", "session_id": session_id, "files": []}).status_code == 422
        assert client.post("/chat/completion", json={"content": "问题", "session_id": "missing"}).status_code == 404
        assert client.get("/qa/tasks").status_code == 404


def test_session_files_bind_upload_and_delete(tmp_path):
    agent = AutoAgent()
    app = create_app(settings=BackendSettings(database_path=tmp_path / "upload.sqlite3"), agent_client=agent)
    with TestClient(app) as client:
        session_id = client.post("/chat/sessions").json()["session_id"]
        uploaded = client.post(f"/chat/sessions/{session_id}/files",
                               files=[("files", ("test.pdf", b"%PDF-1.4", "application/pdf"))])
        assert uploaded.status_code == 200
        rows = uploaded.json()["resources"]
        assert agent.prepared == [(session_id, [{"filename": "test.pdf", "content": b"%PDF-1.4"}], [])]
        assert {row["location"] for row in rows if row["type"] == "raw"} == {f"s3://res_{session_id}/raw/test.pdf"}
        assert client.post(f"/chat/sessions/{session_id}/files", data={"x": "1"}).status_code == 422
        assert client.post("/chat/sessions/missing/files",
                           files=[("files", ("test.pdf", b"%PDF-1.4", "application/pdf"))]).status_code == 404
        assert client.post(f"/chat/sessions/{session_id}/files",
                           files=[("files", ("bad.txt", b"bad", "text/plain"))]).status_code == 422

        raw_id = next(row["id"] for row in rows if row["type"] == "raw")
        removed = client.delete(f"/chat/sessions/{session_id}/files/{raw_id}")
        assert removed.status_code == 200
        assert all(not row["location"].endswith("/raw/test.pdf") for row in removed.json()["resources"])
        assert agent.prepared[-1][2] == [{"type": "raw", "location": f"s3://res_{session_id}/raw/test.pdf"}]
        assert client.delete(f"/chat/sessions/{session_id}/files/missing").status_code == 404


def test_turn_uses_session_resources_after_upload(tmp_path):
    agent = AutoAgent()
    app = create_app(settings=BackendSettings(database_path=tmp_path / "turn.sqlite3"), agent_client=agent)
    with TestClient(app) as client:
        session_id = client.post("/chat/sessions").json()["session_id"]
        uploaded = client.post(f"/chat/sessions/{session_id}/files",
                               files=[("files", ("test.pdf", b"%PDF-1.4", "application/pdf"))]).json()["resources"]
        client.post("/chat/completion", json={"content": "读文档", "session_id": session_id})
        assert app.state.agent_client.requests[0]["resource_path"] == [
            {"type": row["type"], "location": row["location"]} for row in uploaded if row["type"] != "raw"
        ]


def test_http_disconnect_does_not_cancel_background_turn(tmp_path):
    async def scenario():
        agent = FakeAgent()
        app = create_app(settings=BackendSettings(database_path=tmp_path / "disconnect.sqlite3"), agent_client=agent)
        async with app.router.lifespan_context(app):
            session_id = await app.state.session_registry.create_session()
            request_events = asyncio.Queue()
            body = json.dumps({"content": "问题", "session_id": session_id}).encode()
            await request_events.put({"type": "http.request", "body": body, "more_body": False})
            sent = asyncio.Queue()
            scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.0"}, "http_version": "1.1",
                     "method": "POST", "scheme": "http", "path": "/chat/completion", "raw_path": b"/chat/completion",
                     "query_string": b"", "headers": [(b"content-type", b"application/json")],
                     "client": ("127.0.0.1", 1), "server": ("test", 80), "root_path": ""}
            task = asyncio.create_task(app(scope, request_events.get, sent.put))
            while True:
                event = await asyncio.wait_for(sent.get(), 2)
                if event["type"] == "http.response.body" and b"session.snapshot" in event.get("body", b""):
                    snapshot = json.loads(event["body"].decode().split("data: ")[1].strip())
                    break
            call = await agent.created.get()
            await request_events.put({"type": "http.disconnect"})
            await asyncio.wait_for(task, 2)
            assert not call.cancelled
            manager = await app.state.session_registry.get_or_create(snapshot["session_id"])
            context = await manager.attach()
            await call.events.put({"type": "model_message.done", "seq": 1, "message_id": "m", "content": "离线完成"})
            await call.events.put({"type": "completion.completed", "seq": 2})
            await next_type(context.subscription, "turn.completed")
            assert manager.runtime is None
    asyncio.run(scenario())
