from __future__ import annotations

from pathlib import Path

from backend.core.config import BackendSettings


def test_backend_settings_does_not_define_builtin_task_specs(tmp_path: Path):
    settings = BackendSettings(database_path=tmp_path / "backend.sqlite3")

    assert not hasattr(settings, "task_specs")
    assert not hasattr(settings, "task_specs_dir")
