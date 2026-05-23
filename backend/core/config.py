from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class BackendSettings:
    database_path: Path = Path("backend/backend.sqlite3")
    agent_service_base_url: str = "http://localhost:8001"
    agent_request_timeout_seconds: float = 1200.0
    agent_cancel_timeout_seconds: float = 2.0
    supported_file_types: tuple[str, ...] = ("pdf",)

    def __post_init__(self) -> None:
        self.database_path = Path(self.database_path)

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
                os.getenv("AGENT_SERVICE_TIMEOUT_SECONDS", "1200")
            ),
            agent_cancel_timeout_seconds=float(
                os.getenv("AGENT_SERVICE_CANCEL_TIMEOUT_SECONDS", "2")
            ),
        )
