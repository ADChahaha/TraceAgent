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
    (tmp_path / ".env").write_text("STORAGE_PORT=19090\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    recorder = f"""#!{sys.executable}
import json, os, sys, time
from pathlib import Path
with open(os.environ['CALL_LOG'], 'a') as log:
    log.write(json.dumps({{'command': Path(sys.argv[0]).name, 'args': sys.argv[1:],
                          'endpoint': os.getenv('S3_ENDPOINT_URL'), 'pid': os.getpid()}}) + '\\n')
if os.environ.get('KEEP_RUNNING'):
    while True:
        time.sleep(1)
"""
    for name in ("python", "pnpm"):
        executable = bin_dir / name
        executable.write_text(recorder)
        executable.chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}",
               CALL_LOG=str(tmp_path / "calls.jsonl"), ENV_FILE=str(tmp_path / ".env"))
    env.pop("S3_ENDPOINT_URL", None)
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


@pytest.mark.parametrize("external", [False, True])
def test_start_propagates_storage_endpoint_and_cleans_up(sandbox, external):
    root, env = sandbox
    endpoint = "http://storage.example:9000" if external else "http://127.0.0.1:19090"
    if external:
        with (root / ".env").open("a") as config:
            config.write(f"S3_ENDPOINT_URL={endpoint}\n")
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
    finally:
        process.terminate()
        process.communicate(timeout=10)
    for call in calls:
        with pytest.raises(ProcessLookupError):
            os.kill(call["pid"], 0)
