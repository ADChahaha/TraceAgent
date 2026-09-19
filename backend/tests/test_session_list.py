from fastapi.testclient import TestClient

from backend.core.config import BackendSettings
from backend.main import create_app
from backend.tests.test_qa_task_flow import AutoAgent, payloads


def test_sessions_are_visible_to_another_client_after_restart(tmp_path):
    settings = BackendSettings(database_path=tmp_path / "shared.sqlite3")
    with TestClient(create_app(settings=settings, agent_client=AutoAgent())) as first:
        session_id = first.post("/chat/sessions").json()["session_id"]
    with TestClient(create_app(settings=settings, agent_client=AutoAgent())) as second:
        response = second.get("/chat/sessions")
        assert response.status_code == 200
        assert response.json()["sessions"][0]["id"] == session_id
        assert payloads(second.get("/resume", params={"session_id": session_id}))[0]["session_id"] == session_id
        assert second.get("/chat/sessions?limit=0").status_code == 422
        assert second.get("/chat/sessions?limit=201").status_code == 422
