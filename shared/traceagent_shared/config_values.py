"""配置段与基础类型读取辅助：统一遵循 环境变量 > config.toml > 默认值。"""

from __future__ import annotations

import os
from typing import Any


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


def format_host_port(host: str, port: int) -> str:
    formatted_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
    return f"{formatted_host}:{port}"
