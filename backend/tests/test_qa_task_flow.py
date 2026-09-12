"""保留原测试文件路径，业务契约迁移为 completion/resume/cancel。"""

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
        response = client.post("/chat/completion", json={"content": "问题"})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        first = payloads(response)[0]
        session_id = first["session_id"]
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
        assert client.get("/qa/tasks").status_code == 404


def test_multipart_prepares_resource_references(tmp_path):
    app = create_app(settings=BackendSettings(database_path=tmp_path / "upload.sqlite3"), agent_client=AutoAgent())
    with TestClient(app) as client:
        response = client.post("/chat/completion", data={"content": "读文档"}, files={"files": ("test.pdf", b"%PDF-1.4", "application/pdf")})
        assert response.status_code == 200
        assert app.state.agent_client.requests[0]["resource_path"] == [{"type": "documents", "location": "s3://test/documents.zip"}]
        assert client.post("/chat/completion", data={"content": "问题"}, files={"files": ("bad.txt", b"bad")}).status_code == 422


def test_http_disconnect_does_not_cancel_background_turn(tmp_path):
    async def scenario():
        agent = FakeAgent()
        app = create_app(settings=BackendSettings(database_path=tmp_path / "disconnect.sqlite3"), agent_client=agent)
        async with app.router.lifespan_context(app):
            request_events = asyncio.Queue()
            body = json.dumps({"content": "问题"}).encode()
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
            manager = await app.state.session_registry.get_or_load(snapshot["session_id"])
            context = await manager.attach()
            await call.events.put({"type": "model_message.done", "seq": 1, "message_id": "m", "content": "离线完成"})
            await call.events.put({"type": "completion.completed", "seq": 2})
            await next_type(context.subscription, "turn.completed")
            assert manager.current_turn_state is None
    asyncio.run(scenario())
