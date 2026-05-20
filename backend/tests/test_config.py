from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

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
