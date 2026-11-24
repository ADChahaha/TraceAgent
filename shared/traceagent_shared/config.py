"""全仓统一的 `config.toml` 配置加载与环境变量覆盖工具。

配置优先级统一为：显式进程环境变量 > `config.toml` > 代码默认值。
配置文件定位顺序：
1. 函数显式传入 `config_path`（不存在则抛 `FileNotFoundError`）；
2. 进程环境变量 `TRACEAGENT_CONFIG`（显式空串表示禁用配置文件，仅使用环境变量与默认值；非空但不存在则抛 `FileNotFoundError`）；
3. 当前工作目录 `./config.toml`；
4. 仓库根目录 `<repo>/config.toml`。

提供 `python -m traceagent_shared.config --shell-exports <path>` 供启动脚本安全导出配置。
"""

from __future__ import annotations

import argparse
import os
import shlex
import sys
import tomllib
from pathlib import Path
from typing import Any

CONFIG_ENV_VAR = "TRACEAGENT_CONFIG"
DEFAULT_CONFIG_FILENAME = "config.toml"
DEFAULT_GRPC_MAX_MESSAGE_BYTES = 64 * 1024 * 1024
DEFAULT_EMBEDDING_MODEL = "hotchpotch/bekko-embedding-v1-a8m"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_config_path(config_path: str | Path | None = None) -> Path | None:
    """解析生效的配置文件路径；显式路径优先，未指定时按 cwd 与仓库根回退查找。"""
    if config_path is not None:
        return Path(config_path)

    env_path = os.environ.get(CONFIG_ENV_VAR)
    if env_path is not None:
        stripped = env_path.strip()
        if not stripped:
            return None
        return Path(stripped)

    cwd_candidate = Path.cwd() / DEFAULT_CONFIG_FILENAME
    if cwd_candidate.is_file():
        return cwd_candidate

    repo_candidate = _repo_root() / DEFAULT_CONFIG_FILENAME
    if repo_candidate.is_file():
        return repo_candidate
    return None


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """加载 `config.toml` 为字典；隐式探测不存在时返回空字典，显式指定不存在时抛错。"""
    explicit = config_path is not None or (
        CONFIG_ENV_VAR in os.environ and bool(os.environ[CONFIG_ENV_VAR].strip())
    )
    path = resolve_config_path(config_path)
    if path is None:
        return {}
    if not path.is_file():
        if explicit:
            raise FileNotFoundError(f"Config file not found: {path}")
        return {}

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"Invalid TOML syntax in {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"Top-level config in {path} must be a TOML table")
    return data


def get_section(config: dict[str, Any], section: str) -> dict[str, Any]:
    """读取顶层配置段；不存在返回空字典，类型非表时抛 ValueError。"""
    raw = config.get(section)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"Config section [{section}] must be a table")
    return raw


def _section_value(config: dict[str, Any], section: str, key: str) -> Any:
    return get_section(config, section).get(key)


def get_str(
    config: dict[str, Any],
    section: str,
    key: str,
    env_var: str | None,
    default: str,
) -> str:
    """读取非空字符串配置；环境变量或配置文件为空串时回退到默认值。"""
    if env_var and env_var in os.environ:
        env_value = os.environ[env_var]
        return env_value if env_value != "" else default
    raw = _section_value(config, section, key)
    if raw is None:
        return default
    if not isinstance(raw, str):
        raise ValueError(f"[{section}].{key} must be a string")
    return raw if raw != "" else default


def get_raw_str(
    config: dict[str, Any],
    section: str,
    key: str,
    env_var: str | None,
    default: str,
) -> str:
    """读取原始字符串配置，保留显式设置的空串与空白以交由上层做边界校验。"""
    if env_var and env_var in os.environ:
        return os.environ[env_var]
    raw = _section_value(config, section, key)
    if raw is None:
        return default
    if not isinstance(raw, str):
        raise ValueError(f"[{section}].{key} must be a string")
    return raw


def get_optional_str(
    config: dict[str, Any],
    section: str,
    key: str,
    env_var: str | None,
    default: str | None = None,
) -> str | None:
    """读取可选字符串配置；空串视为 None。"""
    if env_var and env_var in os.environ:
        env_value = os.environ[env_var]
        return env_value if env_value != "" else None
    raw = _section_value(config, section, key)
    if raw is None:
        return default
    if not isinstance(raw, str):
        raise ValueError(f"[{section}].{key} must be a string")
    return raw if raw != "" else None


def get_int(
    config: dict[str, Any],
    section: str,
    key: str,
    env_var: str | None,
    default: int,
) -> int:
    """读取整数配置，显式拒绝布尔值。"""
    if env_var and env_var in os.environ:
        env_value = os.environ[env_var]
        if env_value == "":
            return default
        return int(env_value)
    raw = _section_value(config, section, key)
    if raw is None:
        return default
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(f"[{section}].{key} must be an integer")
    return raw


def get_optional_int(
    config: dict[str, Any],
    section: str,
    key: str,
    env_var: str | None,
    default: int | None = None,
) -> int | None:
    """读取可选整数配置；空串视为 None。"""
    if env_var and env_var in os.environ:
        env_value = os.environ[env_var]
        if env_value == "":
            return None
        return int(env_value)
    raw = _section_value(config, section, key)
    if raw is None:
        return default
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(f"[{section}].{key} must be an integer")
    return raw


def get_float(
    config: dict[str, Any],
    section: str,
    key: str,
    env_var: str | None,
    default: float,
) -> float:
    """读取浮点数配置，显式拒绝布尔值。"""
    if env_var and env_var in os.environ:
        env_value = os.environ[env_var]
        if env_value == "":
            return default
        return float(env_value)
    raw = _section_value(config, section, key)
    if raw is None:
        return default
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"[{section}].{key} must be a number")
    return float(raw)


def get_optional_float(
    config: dict[str, Any],
    section: str,
    key: str,
    env_var: str | None,
    default: float | None = None,
) -> float | None:
    """读取可选浮点数配置；空串视为 None。"""
    if env_var and env_var in os.environ:
        env_value = os.environ[env_var]
        if env_value == "":
            return None
        return float(env_value)
    raw = _section_value(config, section, key)
    if raw is None:
        return default
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"[{section}].{key} must be a number")
    return float(raw)


def get_bool(
    config: dict[str, Any],
    section: str,
    key: str,
    env_var: str | None,
    default: bool,
) -> bool:
    """读取布尔配置，支持标准环境变量字符串表示。"""
    if env_var and env_var in os.environ:
        raw_env = os.environ[env_var].strip().lower()
        if raw_env == "":
            return default
        if raw_env in {"1", "true", "yes", "on"}:
            return True
        if raw_env in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"{env_var} must be a boolean value")
    raw = _section_value(config, section, key)
    if raw is None:
        return default
    if not isinstance(raw, bool):
        raise ValueError(f"[{section}].{key} must be a boolean")
    return raw


def _format_host_port(host: str, port: int) -> str:
    formatted_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
    return f"{formatted_host}:{port}"


def resolve_storage_endpoint(config: dict[str, Any]) -> str:
    """解析 S3 endpoint；未显式配置时按 `[storage].host/port` 推导本地地址。"""
    explicit = get_optional_str(config, "storage", "endpoint_url", "S3_ENDPOINT_URL")
    if explicit:
        return explicit
    host = get_str(config, "storage", "host", "STORAGE_HOST", "127.0.0.1")
    port = get_int(config, "storage", "port", "STORAGE_PORT", 9000)
    return f"http://{_format_host_port(host, port)}"


def resolve_agent_target(config: dict[str, Any]) -> str:
    """解析 `backend -> agent` gRPC 目标地址。"""
    explicit = get_optional_str(config, "backend", "agent_service_target", "AGENT_SERVICE_TARGET")
    if explicit:
        return explicit
    host = get_str(config, "agent", "host", "AGENT_HOST", "127.0.0.1")
    port = get_int(config, "agent", "port", "AGENT_PORT", 8001)
    return _format_host_port(host, port)


def resolve_document_target(config: dict[str, Any]) -> str:
    """解析 `backend -> document_service` gRPC 目标地址。"""
    explicit = get_optional_str(config, "backend", "document_service_target", "DOCUMENT_SERVICE_TARGET")
    if explicit:
        return explicit
    host = get_str(config, "document_service", "host", "DOCUMENT_HOST", "127.0.0.1")
    port = get_int(config, "document_service", "port", "DOCUMENT_PORT", 8002)
    return _format_host_port(host, port)


def apply_runtime_env(config_path: str | Path | None = None) -> dict[str, str]:
    """将影响第三方 SDK 的运行期环境变量（如 Hugging Face 开关）按不覆盖原则注入当前进程。"""
    config = load_config(config_path)
    applied: dict[str, str] = {}
    if "HF_HUB_DISABLE_IMPLICIT_TOKEN" not in os.environ:
        if get_bool(config, "huggingface", "disable_implicit_token", None, False):
            os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
            applied["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
    return applied


def collect_shell_exports(config_path: str | Path) -> dict[str, str]:
    """汇总供 `scripts/start.sh` 导出的环境变量表（当前进程已有环境变量优先）。"""
    resolved = Path(config_path).resolve()
    config = load_config(resolved)

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
        CONFIG_ENV_VAR: str(resolved),
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
            get_int(config, "agent", "grpc_max_message_bytes", "AGENT_GRPC_MAX_MESSAGE_BYTES", DEFAULT_GRPC_MAX_MESSAGE_BYTES)
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
                DEFAULT_GRPC_MAX_MESSAGE_BYTES,
            )
        ),
        "DOCUMENT_PROCESSOR_MINERU_LANG": get_str(
            config, "document_service", "mineru_lang", "DOCUMENT_PROCESSOR_MINERU_LANG", "japan"
        ),
        "EMBEDDING_MODEL": get_str(
            config, "document_service", "embedding_model", "EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL
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
            or f"http://{_format_host_port(backend_host, backend_port)}"
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TraceAgent config.toml loader")
    parser.add_argument("--shell-exports", metavar="CONFIG_PATH", help="Emit shell export lines for scripts/start.sh")
    args = parser.parse_args(argv)
    if not args.shell_exports:
        parser.error("--shell-exports is required")
    try:
        exports = collect_shell_exports(args.shell_exports)
    except Exception as exc:
        print(f"Failed to load config {args.shell_exports}: {exc}", file=sys.stderr)
        return 1
    print(format_shell_exports(exports))
    return 0


__all__ = [
    "CONFIG_ENV_VAR",
    "DEFAULT_CONFIG_FILENAME",
    "DEFAULT_EMBEDDING_MODEL",
    "DEFAULT_GRPC_MAX_MESSAGE_BYTES",
    "apply_runtime_env",
    "collect_shell_exports",
    "format_shell_exports",
    "get_bool",
    "get_float",
    "get_int",
    "get_optional_float",
    "get_optional_int",
    "get_optional_str",
    "get_raw_str",
    "get_section",
    "get_str",
    "load_config",
    "resolve_agent_target",
    "resolve_config_path",
    "resolve_document_target",
    "resolve_storage_endpoint",
]


if __name__ == "__main__":
    raise SystemExit(main())
