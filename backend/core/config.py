from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from traceagent_shared.config import (
    DEFAULT_GRPC_MAX_MESSAGE_BYTES,
    get_float,
    get_int,
    get_raw_str,
    load_config,
    resolve_agent_target,
    resolve_document_target,
)

from backend.core.db import validate_database_path


@dataclass(slots=True)
class BackendSettings:
    database_path: Path = Path("backend/backend.sqlite3")
    agent_service_target: str = "127.0.0.1:8001"
    document_service_target: str = "127.0.0.1:8002"
    agent_request_timeout_seconds: float = 1200.0
    document_request_timeout_seconds: float = 1200.0
    agent_cancel_timeout_seconds: float = 2.0
    title_generation_timeout_seconds: float = 15.0
    agent_grpc_max_message_bytes: int = 64 * 1024 * 1024
    document_grpc_max_message_bytes: int = 64 * 1024 * 1024
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
        self.database_path = validate_database_path(self.database_path)
        for name in ("session_command_limit", "subscription_max_events", "subscription_max_bytes",
                     "snapshot_max_bytes", "session_idle_seconds", "sse_heartbeat_seconds",
                     "upload_max_bytes", "upload_max_files", "title_generation_timeout_seconds"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} 必须大于零")

    @classmethod
    def from_env(cls, config_path: str | Path | None = None) -> "BackendSettings":
        config = load_config(config_path)
        raw_database_path = get_raw_str(
            config, "backend", "database_path", "BACKEND_DATABASE_PATH", "backend/backend.sqlite3"
        )
        database_path = validate_database_path(raw_database_path)
        return cls(
            database_path=database_path,
            agent_service_target=resolve_agent_target(config),
            document_service_target=resolve_document_target(config),
            agent_request_timeout_seconds=get_float(
                config, "backend", "agent_service_timeout_seconds", "AGENT_SERVICE_TIMEOUT_SECONDS", 1200.0
            ),
            document_request_timeout_seconds=get_float(
                config, "backend", "document_service_timeout_seconds", "DOCUMENT_SERVICE_TIMEOUT_SECONDS", 1200.0
            ),
            agent_cancel_timeout_seconds=get_float(
                config, "backend", "agent_service_cancel_timeout_seconds", "AGENT_SERVICE_CANCEL_TIMEOUT_SECONDS", 2.0
            ),
            title_generation_timeout_seconds=get_float(
                config, "backend", "title_generation_timeout_seconds", "TITLE_GENERATION_TIMEOUT_SECONDS", 15.0
            ),
            agent_grpc_max_message_bytes=get_int(
                config, "agent", "grpc_max_message_bytes", "AGENT_GRPC_MAX_MESSAGE_BYTES", DEFAULT_GRPC_MAX_MESSAGE_BYTES
            ),
            document_grpc_max_message_bytes=get_int(
                config,
                "document_service",
                "grpc_max_message_bytes",
                "DOCUMENT_GRPC_MAX_MESSAGE_BYTES",
                DEFAULT_GRPC_MAX_MESSAGE_BYTES,
            ),
        )
