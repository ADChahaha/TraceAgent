from __future__ import annotations

from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient

from backend.core.config import BackendSettings
from backend.core.db import initialize_database
from backend.crud.qa_tasks import create_task
from backend.main import create_app


def test_backend_settings_keeps_agent_service_configuration(tmp_path: Path):
    settings = BackendSettings(database_path=tmp_path / "backend.sqlite3")

    assert settings.agent_service_base_url == "http://localhost:8001"
    assert settings.agent_cancel_timeout_seconds == 2.0
    assert settings.supported_file_types == ("pdf", "docx")


def test_backend_settings_loads_agent_cancel_timeout_from_env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("BACKEND_DATABASE_PATH", str(tmp_path / "backend.sqlite3"))
    monkeypatch.setenv("AGENT_SERVICE_CANCEL_TIMEOUT_SECONDS", "0.5")

    settings = BackendSettings.from_env()

    assert settings.agent_cancel_timeout_seconds == 0.5


def test_backend_registers_qa_routes_and_removes_old_task_routes(tmp_path: Path):
    app = create_app(settings=BackendSettings(database_path=tmp_path / "backend.sqlite3"))
    registered_paths = {route.path for route in app.routes}

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


def test_database_initialization_creates_qa_schema_and_drops_old_field_schema():
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
        CREATE TABLE field_traces (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            field_name TEXT NOT NULL
        );
        CREATE TABLE field_routes (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            field_name TEXT NOT NULL,
            route TEXT NOT NULL
        );
        CREATE TABLE reviews (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL
        );
        CREATE TABLE review_fields (
            id TEXT PRIMARY KEY,
            review_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            field_name TEXT NOT NULL
        );
        CREATE TABLE field_commits (
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

    assert {"qa_tasks", "qa_documents", "qa_messages", "qa_turns", "qa_events"} <= table_names
    assert "tasks" not in table_names
    assert "extracted_fields" not in table_names
    assert "field_traces" not in table_names
    assert "field_routes" not in table_names
    assert "reviews" not in table_names
    assert "review_fields" not in table_names
    assert "field_commits" not in table_names
    assert {"id", "status", "stage", "active_turn_id"} <= qa_task_columns
    assert "memory_json" not in qa_task_columns


def test_database_initialization_migrates_existing_qa_tasks_without_memory_json():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE qa_tasks (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            stage TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            memory_json TEXT NOT NULL,
            active_turn_id TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        INSERT INTO qa_tasks (
            id, status, stage, metadata_json, memory_json, active_turn_id,
            error_message, created_at, updated_at
        )
        VALUES (
            'qa_task_old', 'ready', 'ready', '{"source":"old"}', '{}', NULL,
            NULL, '2026-05-24T00:00:00Z', '2026-05-24T00:00:00Z'
        );
        """
    )

    initialize_database(connection)
    created_task = create_task(
        connection,
        task_id="qa_task_new",
        metadata={"source": "new"},
        now="2026-05-24T00:01:00Z",
    )

    qa_task_columns = {row["name"] for row in connection.execute("PRAGMA table_info(qa_tasks)").fetchall()}
    old_task = connection.execute("SELECT * FROM qa_tasks WHERE id = ?", ("qa_task_old",)).fetchone()

    assert "memory_json" not in qa_task_columns
    assert old_task is not None
    assert old_task["metadata_json"] == '{"source":"old"}'
    assert old_task["status"] == "ready"
    assert old_task["stage"] == "ready"
    assert created_task["id"] == "qa_task_new"
