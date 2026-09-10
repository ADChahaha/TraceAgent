from __future__ import annotations

from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient

from backend.core.config import BackendSettings
from backend.core.db import initialize_database
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
    assert settings.supported_file_types == ("pdf", "docx")


def test_backend_settings_loads_agent_target_from_env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("BACKEND_DATABASE_PATH", str(tmp_path / "backend.sqlite3"))
    monkeypatch.setenv("AGENT_SERVICE_TARGET", "agent.internal:50051")

    settings = BackendSettings.from_env()

    assert settings.agent_service_target == "agent.internal:50051"


def test_backend_settings_loads_agent_cancel_timeout_from_env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("BACKEND_DATABASE_PATH", str(tmp_path / "backend.sqlite3"))
    monkeypatch.setenv("AGENT_SERVICE_CANCEL_TIMEOUT_SECONDS", "0.5")

    settings = BackendSettings.from_env()

    assert settings.agent_cancel_timeout_seconds == 0.5


def test_backend_registers_qa_routes_and_removes_old_task_routes(tmp_path: Path):
    app = create_app(settings=BackendSettings(database_path=tmp_path / "backend.sqlite3"))
    registered_paths = _route_paths(app.routes)

    with TestClient(app) as client:
        old_response = client.get("/tasks")

    assert "/qa/tasks" in registered_paths
    assert "/qa/tasks/{task_id}/inputs" in registered_paths
    assert "/qa/tasks/{task_id}/events" in registered_paths
    assert "/qa/tasks/{task_id}/cancel" in registered_paths
    assert "/tasks" not in registered_paths
    assert old_response.status_code == 404


def test_backend_healthz_reports_ok(tmp_path: Path):
    app = create_app(settings=BackendSettings(database_path=tmp_path / "backend.sqlite3"))

    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_database_initialization_creates_qa_schema_without_migrating_legacy_tables():
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
    qa_task_columns = {row["name"] for row in connection.execute("PRAGMA table_info(qa_tasks)").fetchall()}

    assert {"qa_tasks", "qa_resources", "qa_messages", "qa_turns", "qa_events"} <= table_names
    assert qa_task_columns == {"id", "status", "active_turn_id", "created_at", "updated_at"}
    # 初始化只负责建当前 schema，不再清理或迁移旧表；旧库按“重建新库”处理。
    assert "tasks" in table_names
    assert "extracted_fields" in table_names
