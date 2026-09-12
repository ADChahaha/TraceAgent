from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class BackendSettings:
    database_path: Path = Path("backend/backend.sqlite3")
    agent_service_target: str = "127.0.0.1:8001"
    agent_request_timeout_seconds: float = 1200.0
    agent_cancel_timeout_seconds: float = 2.0
    agent_grpc_max_message_bytes: int = 64 * 1024 * 1024
    supported_file_types: tuple[str, ...] = ("pdf", "docx")
    session_command_limit: int = 64
    subscription_max_events: int = 256
    subscription_max_bytes: int = 4 * 1024 * 1024
    snapshot_max_bytes: int = 32 * 1024 * 1024
    session_idle_seconds: float = 60.0
    sse_heartbeat_seconds: float = 15.0
    upload_max_bytes: int = 32 * 1024 * 1024
    upload_max_files: int = 20

    def __post_init__(self) -> None:
        self.database_path = Path(self.database_path)
        for name in ("session_command_limit", "subscription_max_events", "subscription_max_bytes",
                     "snapshot_max_bytes", "session_idle_seconds", "sse_heartbeat_seconds",
                     "upload_max_bytes", "upload_max_files"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} 必须大于零")

    @classmethod
    def from_env(cls) -> "BackendSettings":
        database_path = Path(
            os.getenv("BACKEND_DATABASE_PATH", "backend/backend.sqlite3")
        )
        return cls(
            database_path=database_path,
            agent_service_target=os.getenv(
                "AGENT_SERVICE_TARGET",
                "127.0.0.1:8001",
            ),
            agent_request_timeout_seconds=float(
                os.getenv("AGENT_SERVICE_TIMEOUT_SECONDS", "1200")
            ),
            agent_cancel_timeout_seconds=float(
                os.getenv("AGENT_SERVICE_CANCEL_TIMEOUT_SECONDS", "2")
            ),
            agent_grpc_max_message_bytes=int(
                os.getenv("AGENT_GRPC_MAX_MESSAGE_BYTES", str(64 * 1024 * 1024))
            ),
        )
