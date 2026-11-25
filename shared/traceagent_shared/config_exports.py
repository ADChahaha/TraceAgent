"""供 `scripts/start.sh` 使用的配置环境变量汇总与 POSIX shell 转义导出。"""

from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Any, Callable

from traceagent_shared.config_values import (
    format_host_port,
    get_bool,
    get_float,
    get_int,
    get_optional_str,
    get_raw_str,
    get_str,
)


def resolve_storage_endpoint(config: dict[str, Any]) -> str:
    """解析 S3 endpoint；未显式配置时按 `[storage].host/port` 推导本地地址。"""
    explicit = get_optional_str(config, "storage", "endpoint_url", "S3_ENDPOINT_URL")
    if explicit:
        return explicit
    host = get_str(config, "storage", "host", "STORAGE_HOST", "127.0.0.1")
    port = get_int(config, "storage", "port", "STORAGE_PORT", 9000)
    return f"http://{format_host_port(host, port)}"


def resolve_agent_target(config: dict[str, Any]) -> str:
    """解析 `backend -> agent` gRPC 目标地址。"""
    explicit = get_optional_str(config, "backend", "agent_service_target", "AGENT_SERVICE_TARGET")
    if explicit:
        return explicit
    host = get_str(config, "agent", "host", "AGENT_HOST", "127.0.0.1")
    port = get_int(config, "agent", "port", "AGENT_PORT", 8001)
    return format_host_port(host, port)


def resolve_document_target(config: dict[str, Any]) -> str:
    """解析 `backend -> document_service` gRPC 目标地址。"""
    explicit = get_optional_str(config, "backend", "document_service_target", "DOCUMENT_SERVICE_TARGET")
    if explicit:
        return explicit
    host = get_str(config, "document_service", "host", "DOCUMENT_HOST", "127.0.0.1")
    port = get_int(config, "document_service", "port", "DOCUMENT_PORT", 8002)
    return format_host_port(host, port)


def build_shell_exports(
    config_path: str | Path,
    *,
    loader: Callable[[str | Path], dict[str, Any]],
    config_env_var: str,
    default_grpc_max_bytes: int,
    default_embedding_model: str,
) -> dict[str, str]:
    """汇总供 `scripts/start.sh` 导出的环境变量表（当前进程已有环境变量优先）。"""
    resolved = Path(config_path).resolve()
    config = loader(resolved)

    storage_host = get_str(config, "storage", "host", "STORAGE_HOST", "127.0.0.1")
    storage_port = get_int(config, "storage", "port", "STORAGE_PORT", 9000)
    agent_host = get_str(config, "agent", "host", "AGENT_HOST", "127.0.0.1")
    agent_port = get_int(config, "agent", "port", "AGENT_PORT", 8001)
    document_host = get_str(config, "document_service", "host", "DOCUMENT_HOST", "127.0.0.1")
    document_port = get_int(config, "document_service", "port", "DOCUMENT_PORT", 8002)
    backend_host = get_str(config, "backend", "host", "BACKEND_HOST", "127.0.0.1")
    backend_port = get_int(config, "backend", "port", "BACKEND_PORT", 8000)
    frontend_host = get_str(config, "frontend", "host", "FRONTEND_HOST", "127.0.0.1")
    frontend_port = get_int(config, "frontend", "port", "FRONTEND_PORT", 3000)

    exports: dict[str, str] = {
        config_env_var: str(resolved),
        "STORAGE_HOST": storage_host,
        "STORAGE_PORT": str(storage_port),
        "S3_ENDPOINT_URL": get_optional_str(config, "storage", "endpoint_url", "S3_ENDPOINT_URL") or "",
        "S3_ACCESS_KEY": get_str(config, "storage", "access_key", "S3_ACCESS_KEY", "minioadmin"),
        "S3_SECRET_KEY": get_str(config, "storage", "secret_key", "S3_SECRET_KEY", "minioadmin"),
        "S3_BUCKET_PREFIX": get_optional_str(config, "storage", "bucket_prefix", "S3_BUCKET_PREFIX") or "",
        "AGENT_HOST": agent_host,
        "AGENT_PORT": str(agent_port),
        "AGENT_GRPC_WORKERS": str(get_int(config, "agent", "grpc_workers", "AGENT_GRPC_WORKERS", 16)),
        "AGENT_GRPC_MAX_MESSAGE_BYTES": str(
            get_int(config, "agent", "grpc_max_message_bytes", "AGENT_GRPC_MAX_MESSAGE_BYTES", default_grpc_max_bytes)
        ),
        "DOCUMENT_HOST": document_host,
        "DOCUMENT_PORT": str(document_port),
        "DOCUMENT_GRPC_WORKERS": str(
            get_int(config, "document_service", "grpc_workers", "DOCUMENT_GRPC_WORKERS", 16)
        ),
        "DOCUMENT_GRPC_MAX_MESSAGE_BYTES": str(
            get_int(
                config,
                "document_service",
                "grpc_max_message_bytes",
                "DOCUMENT_GRPC_MAX_MESSAGE_BYTES",
                default_grpc_max_bytes,
            )
        ),
        "DOCUMENT_PROCESSOR_MINERU_LANG": get_str(
            config, "document_service", "mineru_lang", "DOCUMENT_PROCESSOR_MINERU_LANG", "japan"
        ),
        "EMBEDDING_MODEL": get_str(
            config, "document_service", "embedding_model", "EMBEDDING_MODEL", default_embedding_model
        ),
        "EMBEDDING_BACKEND": get_str(
            config, "document_service", "embedding_backend", "EMBEDDING_BACKEND", "openvino"
        ),
        "EMBEDDING_CHUNK_SIZE": str(
            get_int(config, "document_service", "embedding_chunk_size", "EMBEDDING_CHUNK_SIZE", 256)
        ),
        "EMBEDDING_CHUNK_OVERLAP": str(
            get_int(config, "document_service", "embedding_chunk_overlap", "EMBEDDING_CHUNK_OVERLAP", 32)
        ),
        "BACKEND_HOST": backend_host,
        "BACKEND_PORT": str(backend_port),
        "BACKEND_DATABASE_PATH": get_raw_str(
            config, "backend", "database_path", "BACKEND_DATABASE_PATH", "backend/backend.sqlite3"
        ),
        "AGENT_SERVICE_TARGET": resolve_agent_target(config),
        "DOCUMENT_SERVICE_TARGET": resolve_document_target(config),
        "AGENT_SERVICE_TIMEOUT_SECONDS": str(
            get_float(config, "backend", "agent_service_timeout_seconds", "AGENT_SERVICE_TIMEOUT_SECONDS", 1200.0)
        ),
        "DOCUMENT_SERVICE_TIMEOUT_SECONDS": str(
            get_float(
                config, "backend", "document_service_timeout_seconds", "DOCUMENT_SERVICE_TIMEOUT_SECONDS", 1200.0
            )
        ),
        "AGENT_SERVICE_CANCEL_TIMEOUT_SECONDS": str(
            get_float(
                config,
                "backend",
                "agent_service_cancel_timeout_seconds",
                "AGENT_SERVICE_CANCEL_TIMEOUT_SECONDS",
                2.0,
            )
        ),
        "FRONTEND_HOST": frontend_host,
        "FRONTEND_PORT": str(frontend_port),
        "BACKEND_BASE_URL": (
            get_optional_str(config, "frontend", "backend_base_url", "BACKEND_BASE_URL")
            or f"http://{format_host_port(backend_host, backend_port)}"
        ),
    }

    optional_pairs = (
        ("STORAGE_DATA_ROOT", get_optional_str(config, "storage", "data_root", "STORAGE_DATA_ROOT")),
        (
            "DOCUMENT_RESOURCES_ROOT",
            get_optional_str(config, "document_service", "resources_root", "DOCUMENT_RESOURCES_ROOT"),
        ),
        ("MINERU_BIN", get_optional_str(config, "document_service", "mineru_bin", "MINERU_BIN")),
    )
    for env_name, value in optional_pairs:
        if value:
            exports[env_name] = value

    if "HF_HUB_DISABLE_IMPLICIT_TOKEN" in os.environ:
        exports["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"]
    elif get_bool(config, "huggingface", "disable_implicit_token", None, False):
        exports["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"

    return exports


def format_shell_exports(exports: dict[str, str]) -> str:
    """将环境变量字典格式化为安全转义的 POSIX shell export 语句。"""
    return "\n".join(f"export {key}={shlex.quote(value)}" for key, value in exports.items())
