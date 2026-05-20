from __future__ import annotations

from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient

from backend.core.db import initialize_database
from backend.core.config import BackendSettings
from backend.main import create_app


def test_backend_settings_does_not_define_builtin_task_specs(tmp_path: Path):
    settings = BackendSettings(database_path=tmp_path / "backend.sqlite3")

    assert not hasattr(settings, "task_specs")
    assert not hasattr(settings, "task_specs_dir")


def test_backend_does_not_register_builtin_experiment_routes(tmp_path: Path):
    app = create_app(settings=BackendSettings(database_path=tmp_path / "backend.sqlite3"))
    registered_paths = {route.path for route in app.routes}

    with TestClient(app) as client:
        response = client.get("/experiments/contract-nli")

    assert all(not path.startswith("/experiments/") for path in registered_paths)
    assert response.status_code == 404


def test_backend_does_not_register_manual_check_routes(tmp_path: Path):
    app = create_app(settings=BackendSettings(database_path=tmp_path / "backend.sqlite3"))
    registered_paths = {route.path for route in app.routes}

    assert "/tasks/{task_id}/review" not in registered_paths
    assert all("review" not in path for path in registered_paths)


def test_database_initialization_removes_legacy_route_and_review_schema():
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
        CREATE TABLE field_routes (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            field_name TEXT NOT NULL,
            route TEXT NOT NULL,
            route_reason TEXT NOT NULL,
            needs_review INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE reviews (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            decision TEXT NOT NULL,
            comment TEXT,
            reviewer TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE review_fields (
            id TEXT PRIMARY KEY,
            review_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            field_name TEXT NOT NULL,
            agent_value_json TEXT,
            review_value_json TEXT,
            final_value_json TEXT,
            decision TEXT NOT NULL,
            comment TEXT
        );
        CREATE TABLE field_commits (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            field_name TEXT NOT NULL,
            final_value_json TEXT,
            route TEXT NOT NULL,
            reviewed INTEGER NOT NULL,
            review_decision TEXT,
            agent_value_json TEXT,
            review_value_json TEXT,
            evidence_refs_json TEXT NOT NULL,
            used_global_lookup INTEGER NOT NULL,
            used_validation_rule INTEGER NOT NULL,
            related_fields_json TEXT NOT NULL,
            committed_by TEXT NOT NULL,
            committed_at TEXT NOT NULL
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
    task_columns = {row["name"] for row in connection.execute("PRAGMA table_info(tasks)").fetchall()}
    commit_columns = {row["name"] for row in connection.execute("PRAGMA table_info(field_commits)").fetchall()}

    assert "field_routes" not in table_names
    assert "reviews" not in table_names
    assert "review_fields" not in table_names
    assert "route" not in task_columns
    assert "route_reason" not in task_columns
    assert "route" not in commit_columns
    assert "reviewed" not in commit_columns
    assert "review_decision" not in commit_columns
    assert "review_value_json" not in commit_columns
