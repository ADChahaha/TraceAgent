"""全仓统一的 `config.toml` 配置加载与环境变量覆盖入口。

配置优先级统一为：显式进程环境变量 > `config.toml` > 代码默认值。
提供 `python -m traceagent_shared.config --shell-exports <path>` 供启动脚本安全导出配置。
"""

from __future__ import annotations

import argparse
import os
import sys
import tomllib
from pathlib import Path
from typing import Any

from traceagent_shared.config_exports import (
    build_shell_exports,
    format_shell_exports,
    resolve_agent_target,
    resolve_document_target,
    resolve_storage_endpoint,
)
from traceagent_shared.config_values import (
    get_bool,
    get_float,
    get_int,
    get_optional_float,
    get_optional_int,
    get_optional_str,
    get_raw_str,
    get_section,
    get_str,
)

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
    return build_shell_exports(
        config_path,
        loader=load_config,
        config_env_var=CONFIG_ENV_VAR,
        default_grpc_max_bytes=DEFAULT_GRPC_MAX_MESSAGE_BYTES,
        default_embedding_model=DEFAULT_EMBEDDING_MODEL,
    )


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
