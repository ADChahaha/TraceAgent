"""在隔离目录执行脚本，验证安装参数、服务启动和环境传递。"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import pytest


@pytest.fixture
def sandbox(tmp_path):
    root = Path(__file__).resolve().parents[2]
    shutil.copytree(root / "scripts", tmp_path / "scripts")
    (tmp_path / "frontend/.next").mkdir(parents=True)
    (tmp_path / "frontend/.next/BUILD_ID").write_text("test")
    (tmp_path / "config.toml").write_text(
        "[storage]\nport = 19090\n\n[huggingface]\ndisable_implicit_token = true\n",
        encoding="utf-8",
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    recorder = f"""#!{sys.executable}
import json, os, subprocess, sys, time
from pathlib import Path
if Path(sys.argv[0]).name == 'python' and sys.argv[1:3] == ['-m', 'traceagent_shared.config']:
    raise SystemExit(subprocess.call([{sys.executable!r}, *sys.argv[1:]]))
with open(os.environ['CALL_LOG'], 'a') as log:
    log.write(json.dumps({{
        'command': Path(sys.argv[0]).name,
        'args': sys.argv[1:],
        'endpoint': os.getenv('S3_ENDPOINT_URL'),
        'config': os.getenv('TRACEAGENT_CONFIG'),
        'hf_disable': os.getenv('HF_HUB_DISABLE_IMPLICIT_TOKEN'),
        'pid': os.getpid(),
    }}) + '\\n')
if os.environ.get('KEEP_RUNNING'):
    while True:
        time.sleep(1)
"""
    for name in ("python", "pnpm"):
        executable = bin_dir / name
        executable.write_text(recorder)
        executable.chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}",
               CALL_LOG=str(tmp_path / "calls.jsonl"), CONFIG_FILE=str(tmp_path / "config.toml"))
    for key in ("S3_ENDPOINT_URL", "STORAGE_PORT", "TRACEAGENT_CONFIG", "HF_HUB_DISABLE_IMPLICIT_TOKEN"):
        env.pop(key, None)
    return tmp_path, env


def test_install_includes_storage_and_embedding_dependencies(sandbox):
    root, env = sandbox
    subprocess.run(["bash", str(root / "scripts/install.sh")], env=env, check=True,
                   capture_output=True, text=True)
    calls = [json.loads(line) for line in (root / "calls.jsonl").read_text().splitlines()]
    packages = [arg for call in calls if call["command"] == "python" for arg in call["args"]]
    assert "./storage" in packages
    assert "agent[dev,embeddings]" in packages
    assert "document_service[dev,embeddings]" in packages


def test_start_fails_clearly_when_config_toml_missing(sandbox):
    root, env = sandbox
    (root / "config.toml").unlink()
    result = subprocess.run(
        ["bash", str(root / "scripts/start.sh")],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Missing config file" in result.stdout + result.stderr


@pytest.mark.parametrize("external", [False, True])
def test_start_propagates_storage_endpoint_and_cleans_up(sandbox, external):
    root, env = sandbox
    endpoint = "http://storage.example:9000" if external else "http://127.0.0.1:19090"
    if external:
        (root / "config.toml").write_text(
            f'[storage]\nport = 19090\nendpoint_url = "{endpoint}"\n\n'
            "[huggingface]\ndisable_implicit_token = true\n",
            encoding="utf-8",
        )
    env["KEEP_RUNNING"] = "1"
    process = subprocess.Popen(["bash", str(root / "scripts/start.sh")], env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    calls = []
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if (root / "calls.jsonl").exists():
                calls = [json.loads(line) for line in (root / "calls.jsonl").read_text().splitlines()]
            if any(call["command"] == "pnpm" for call in calls) or process.poll() is not None:
                break
            time.sleep(.05)
        assert any(call["command"] == "pnpm" for call in calls), "前端启动前脚本异常退出"
        storage_calls = [call for call in calls if "storage.main:create_app" in call["args"]]
        assert len(storage_calls) == (0 if external else 1)
        if not external:
            assert calls[0] == storage_calls[0]
            assert "--factory" in calls[0]["args"]
            assert calls[0]["args"][-2:] == ["--port", "19090"]
        assert all(call["endpoint"] == endpoint for call in calls)
        assert all(call["config"] == str((root / "config.toml").resolve()) for call in calls)
        assert all(call["hf_disable"] == "1" for call in calls)
    finally:
        process.terminate()
        process.communicate(timeout=10)
    for call in calls:
        with pytest.raises(ProcessLookupError):
            os.kill(call["pid"], 0)
