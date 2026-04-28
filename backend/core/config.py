from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_TASK_SPECS: dict[str, dict[str, Any]] = {
    "civilized_dormitory": {
        "task_name": "civilized_dormitory",
        "fields": [
            {
                "field_name": "room_numbers",
                "display_name": "文明寝室房间号",
                "type": "string",
                "required": True,
                "critical": True,
            }
        ],
    }
}


@dataclass(slots=True)
class BackendSettings:
    database_path: Path = Path("backend/backend.sqlite3")
    agent_service_base_url: str = "http://localhost:8001"
    agent_request_timeout_seconds: float = 60.0
    supported_file_types: tuple[str, ...] = ("pdf", "docx")
    task_specs: dict[str, dict[str, Any]] = field(
        default_factory=lambda: dict(DEFAULT_TASK_SPECS)
    )

    @classmethod
    def from_env(cls) -> "BackendSettings":
        database_path = Path(
            os.getenv("BACKEND_DATABASE_PATH", "backend/backend.sqlite3")
        )
        return cls(
            database_path=database_path,
            agent_service_base_url=os.getenv(
                "AGENT_SERVICE_BASE_URL",
                "http://localhost:8001",
            ),
            agent_request_timeout_seconds=float(
                os.getenv("AGENT_SERVICE_TIMEOUT_SECONDS", "60")
            ),
        )

