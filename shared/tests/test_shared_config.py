"""统一 config.toml 加载器、环境变量覆盖、默认值推导与 shell 导出测试。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from traceagent_shared.config import (
    CONFIG_ENV_VAR,
    apply_runtime_env,
    collect_shell_exports,
    format_shell_exports,
    get_bool,
    get_float,
    get_int,
    get_optional_str,
    get_str,
    load_config,
    resolve_agent_target,
    resolve_document_target,
    resolve_storage_endpoint,
)


def test_load_config_reads_explicit_toml_and_env_overrides(monkeypatch, tmp_path: Path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        """
[storage]
host = "127.0.0.1"
port = 19000
bucket_prefix = "cfg-"

[agent]
host = "127.0.0.1"
port = 18001

[document_service]
host = "127.0.0.1"
port = 18002

[huggingface]
disable_implicit_token = true
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv(CONFIG_ENV_VAR, str(cfg_path))
    for key in (
        "STORAGE_HOST",
        "STORAGE_PORT",
        "S3_ENDPOINT_URL",
        "S3_BUCKET_PREFIX",
        "AGENT_HOST",
        "AGENT_PORT",
        "AGENT_SERVICE_TARGET",
        "DOCUMENT_HOST",
        "DOCUMENT_PORT",
        "DOCUMENT_SERVICE_TARGET",
        "HF_HUB_DISABLE_IMPLICIT_TOKEN",
    ):
        monkeypatch.delenv(key, raising=False)

    config = load_config()
    assert get_int(config, "storage", "port", "STORAGE_PORT", 9000) == 19000
    assert resolve_storage_endpoint(config) == "http://127.0.0.1:19000"
    assert resolve_agent_target(config) == "127.0.0.1:18001"
    assert resolve_document_target(config) == "127.0.0.1:18002"
    assert get_bool(config, "huggingface", "disable_implicit_token", None, False) is True

    monkeypatch.setenv("S3_ENDPOINT_URL", "http://external-s3:9000")
    monkeypatch.setenv("STORAGE_PORT", "29000")
    monkeypatch.setenv("AGENT_SERVICE_TARGET", "agent.override:50051")
    assert get_int(config, "storage", "port", "STORAGE_PORT", 9000) == 29000
    assert resolve_storage_endpoint(config) == "http://external-s3:9000"
    assert resolve_agent_target(config) == "agent.override:50051"


def test_load_config_rejects_missing_explicit_path_and_invalid_types(monkeypatch, tmp_path: Path):
    missing = tmp_path / "missing.toml"
    monkeypatch.setenv(CONFIG_ENV_VAR, str(missing))
    with pytest.raises(FileNotFoundError):
        load_config()

    bad_toml = tmp_path / "bad.toml"
    bad_toml.write_text("[model\nfoo = 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid TOML"):
        load_config(bad_toml)

    bad_types = tmp_path / "types.toml"
    bad_types.write_text("[agent]\nport = true\n[model]\ntemperature = false\n", encoding="utf-8")
    loaded = load_config(bad_types)
    with pytest.raises(ValueError, match="integer"):
        get_int(loaded, "agent", "port", None, 8001)
    with pytest.raises(ValueError, match="number"):
        get_float(loaded, "model", "temperature", None, 0.0)


def test_empty_env_disables_file_loading(monkeypatch):
    monkeypatch.setenv(CONFIG_ENV_VAR, "")
    assert load_config() == {}


def test_apply_runtime_env_sets_hf_flag_without_overwriting_env(monkeypatch, tmp_path: Path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("[huggingface]\ndisable_implicit_token = true\n", encoding="utf-8")
    monkeypatch.delenv("HF_HUB_DISABLE_IMPLICIT_TOKEN", raising=False)

    applied = apply_runtime_env(cfg_path)
    assert applied == {"HF_HUB_DISABLE_IMPLICIT_TOKEN": "1"}
    assert get_optional_str({}, "huggingface", "disable_implicit_token", "HF_HUB_DISABLE_IMPLICIT_TOKEN") == "1"

    monkeypatch.setenv("HF_HUB_DISABLE_IMPLICIT_TOKEN", "0")
    assert apply_runtime_env(cfg_path) == {}
    assert get_str({}, "huggingface", "disable_implicit_token", "HF_HUB_DISABLE_IMPLICIT_TOKEN", "1") == "0"


def test_cli_shell_exports_emits_escaped_values_and_hf_toggle(monkeypatch, tmp_path: Path):
    for key in ("S3_ENDPOINT_URL", "S3_BUCKET_PREFIX", "STORAGE_PORT", "HF_HUB_DISABLE_IMPLICIT_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        """
[storage]
port = 19090
bucket_prefix = "team a"

[huggingface]
disable_implicit_token = true
""".strip(),
        encoding="utf-8",
    )
    exports = collect_shell_exports(cfg_path)
    assert exports["STORAGE_PORT"] == "19090"
    assert exports["S3_ENDPOINT_URL"] == ""
    assert exports["S3_BUCKET_PREFIX"] == "team a"
    assert exports["HF_HUB_DISABLE_IMPLICIT_TOKEN"] == "1"
    formatted = format_shell_exports(exports)
    assert "export S3_BUCKET_PREFIX='team a'" in formatted

    result = subprocess.run(
        [sys.executable, "-m", "traceagent_shared.config", "--shell-exports", str(cfg_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "export STORAGE_PORT=19090" in result.stdout
    assert "export HF_HUB_DISABLE_IMPLICIT_TOKEN=1" in result.stdout
