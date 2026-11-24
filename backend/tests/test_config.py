from __future__ import annotations

from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient
import pytest

from backend.core.config import BackendSettings
from backend.core.db import ThreadLocalDatabase, connect_database, initialize_database
from backend.main import create_app


def _route_paths(routes) -> set[str]:
    paths: set[str] = set()
    stack = list(routes)
    while stack:
        route = stack.pop()
        path = getattr(route, "path", None)
        if path is not None:
            paths.add(path)
        subroutes = getattr(route, "routes", None)
        if subroutes:
            stack.extend(subroutes)
        original_router = getattr(route, "original_router", None)
        if original_router is not None:
            stack.extend(getattr(original_router, "routes", []))
    return paths


def test_backend_settings_keeps_agent_service_configuration(tmp_path: Path):
    settings = BackendSettings(database_path=tmp_path / "backend.sqlite3")

    assert settings.agent_service_target == "127.0.0.1:8001"
    assert settings.agent_request_timeout_seconds == 1200.0
    assert settings.agent_cancel_timeout_seconds == 2.0
    assert settings.agent_grpc_max_message_bytes == 64 * 1024 * 1024
    assert settings.document_service_target == "127.0.0.1:8002"
    assert settings.document_request_timeout_seconds == 1200.0
    assert settings.document_grpc_max_message_bytes == 64 * 1024 * 1024
    assert settings.supported_file_types == ("pdf", "docx")


def test_backend_settings_loads_agent_grpc_message_limit_from_env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("BACKEND_DATABASE_PATH", str(tmp_path / "backend.sqlite3"))
    monkeypatch.setenv("AGENT_GRPC_MAX_MESSAGE_BYTES", "1048576")

    settings = BackendSettings.from_env()

    assert settings.agent_grpc_max_message_bytes == 1048576


def test_backend_settings_loads_agent_target_from_env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("BACKEND_DATABASE_PATH", str(tmp_path / "backend.sqlite3"))
    monkeypatch.setenv("AGENT_SERVICE_TARGET", "agent.internal:50051")

    settings = BackendSettings.from_env()

    assert settings.agent_service_target == "agent.internal:50051"


def test_backend_settings_loads_document_service_configuration(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("BACKEND_DATABASE_PATH", str(tmp_path / "backend.sqlite3"))
    monkeypatch.setenv("DOCUMENT_SERVICE_TARGET", "document.internal:50052")
    monkeypatch.setenv("DOCUMENT_SERVICE_TIMEOUT_SECONDS", "900")
    monkeypatch.setenv("DOCUMENT_GRPC_MAX_MESSAGE_BYTES", "2097152")

    settings = BackendSettings.from_env()

    assert settings.document_service_target == "document.internal:50052"
    assert settings.document_request_timeout_seconds == 900.0
    assert settings.document_grpc_max_message_bytes == 2097152


def test_backend_settings_loads_agent_cancel_timeout_from_env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("BACKEND_DATABASE_PATH", str(tmp_path / "backend.sqlite3"))
    monkeypatch.setenv("AGENT_SERVICE_CANCEL_TIMEOUT_SECONDS", "0.5")

    settings = BackendSettings.from_env()

    assert settings.agent_cancel_timeout_seconds == 0.5


def test_backend_registers_chat_completion_resume_cancel(tmp_path: Path):
    app = create_app(settings=BackendSettings(database_path=tmp_path / "backend.sqlite3"))
    registered_paths = _route_paths(app.routes)

    with TestClient(app) as client:
        old_response = client.get("/tasks")

    assert {"/chat/completion", "/resume", "/cancel"} <= registered_paths
    assert "/qa/tasks" not in registered_paths
    assert "/tasks" not in registered_paths
    assert old_response.status_code == 404


def test_backend_healthz_reports_ok(tmp_path: Path):
    app = create_app(settings=BackendSettings(database_path=tmp_path / "backend.sqlite3"))

    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_database_initialization_creates_chat_schema_without_migrating_legacy_tables():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY,
            task_type TEXT NOT NULL,
            status TEXT NOT NULL,
            stage TEXT NOT NULL,
            route TEXT,
            route_reason TEXT,
            metadata_json TEXT NOT NULL,
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT
        );
        CREATE TABLE extracted_fields (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            field_name TEXT NOT NULL
        );
        """
    )

    initialize_database(connection)

    table_names = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    chat_session_columns = {row["name"] for row in connection.execute("PRAGMA table_info(chat_sessions)").fetchall()}

    assert {"chat_sessions", "chat_resources", "chat_messages", "chat_turns"} <= table_names
    assert chat_session_columns == {"id", "status", "active_turn_id", "created_at", "updated_at"}
    # 初始化只负责建当前 schema，不再清理或迁移旧表；旧库按"重建新库"处理。
    assert "tasks" in table_names
    assert "extracted_fields" in table_names


@pytest.mark.parametrize(
    "invalid_path",
    [
        ":memory:",
        " :MEMORY: ",
        "",
        "   ",
        ".",
        "file::memory:?cache=shared",
        "file:traceagent?mode=memory",
    ],
)
def test_backend_rejects_in_memory_and_invalid_database_paths(monkeypatch, invalid_path: str):
    with pytest.raises(ValueError, match="不支持内存数据库"):
        BackendSettings(database_path=Path(invalid_path))
    with pytest.raises(ValueError, match="不支持内存数据库"):
        ThreadLocalDatabase(invalid_path)
    with pytest.raises(ValueError, match="不支持内存数据库"):
        connect_database(invalid_path)

    monkeypatch.setenv("BACKEND_DATABASE_PATH", invalid_path)
    with pytest.raises(ValueError, match="不支持内存数据库"):
        BackendSettings.from_env()


def test_backend_rejects_directory_as_database_path(tmp_path: Path):
    with pytest.raises(ValueError, match="不能是目录"):
        BackendSettings(database_path=tmp_path)
    with pytest.raises(ValueError, match="不能是目录"):
        ThreadLocalDatabase(tmp_path)


def test_backend_lifespan_recovers_and_serves_sessions_across_worker_threads(tmp_path: Path):
    app = create_app(settings=BackendSettings(database_path=tmp_path / "lifespan.sqlite3"))

    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        created = client.post("/chat/sessions")
        assert created.status_code == 200
        session_id = created.json()["session_id"]
        listed = client.get("/chat/sessions")
        assert listed.status_code == 200
        assert [row["id"] for row in listed.json()["sessions"]] == [session_id]
