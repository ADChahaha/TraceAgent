"""检查 CI 安装依赖与仓库服务边界一致，并实际执行 OCR 模块导入。"""

import ast
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tomllib

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
JOBS = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]


def editable_packages(job):
    packages = {}
    for step in JOBS[job]["steps"]:
        for line in step.get("run", "").splitlines():
            if not line.strip().startswith("python -m pip install "):
                continue
            args = shlex.split(line)
            for index, argument in enumerate(args):
                if argument != "-e":
                    continue
                path, _, extras = args[index + 1].partition("[")
                metadata = tomllib.loads((ROOT / path / "pyproject.toml").read_text())
                packages[metadata["project"]["name"]] = (metadata["project"], set(extras.rstrip("]").split(",")))
    return packages


@pytest.mark.parametrize("job", ["backend", "agent-ocr-install"])
def test_install_includes_local_dependency_closure(job):
    local_names = {
        tomllib.loads(path.read_text())["project"]["name"]
        for path in ROOT.glob("*/pyproject.toml")
    }
    packages = editable_packages(job)
    for project, _ in packages.values():
        for dependency in project.get("dependencies", []):
            name = dependency.split("==")[0]
            if name in local_names:
                assert name in packages, f"{job}: {project['name']} 缺少本地依赖 {name}"


def test_agent_install_supports_storage_fixtures_and_embedding_startup():
    packages = editable_packages("agent-ocr-install")
    assert "traceagent-storage" in packages, "测试夹具需要真实 storage 服务"
    for name in ("agent-service", "traceagent-document-service"):
        assert "embeddings" in packages[name][1], f"{name} 缺少默认 embedding 运行时"


def test_ocr_smoke_imports_current_converter():
    step = next(step for step in JOBS["agent-ocr-install"]["steps"]
                if step["name"] == "Verify OCR dependency imports")
    source = step["run"].split("python - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    imports = [node for node in ast.parse(source).body if isinstance(node, ast.ImportFrom)
               and any(alias.name == "resolve_mineru_lang" for alias in node.names)]
    assert len(imports) == 1, "OCR 检查必须导入真实转换器"
    code = ast.unparse(imports[0]) + "\nassert resolve_mineru_lang() == 'japan'\n"
    env = dict(os.environ, **step.get("env", {}))
    env.pop("DOCUMENT_PROCESSOR_MINERU_LANG", None)
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_ci_configures_file_backed_backend_database_and_checks_sessions():
    configured: list[tuple[str, str]] = []
    for job_name, job in JOBS.items():
        if "BACKEND_DATABASE_PATH" in (job.get("env") or {}):
            configured.append((f"{job_name}.env", str(job["env"]["BACKEND_DATABASE_PATH"])))
        for step in job.get("steps", []):
            step_label = f"{job_name}.{step.get('name', 'unnamed')}"
            if "BACKEND_DATABASE_PATH" in (step.get("env") or {}):
                configured.append((f"{step_label}.env", str(step["env"]["BACKEND_DATABASE_PATH"])))
            run_script = step.get("run", "")
            for match in re.finditer(r"^\s*(?:export\s+)?BACKEND_DATABASE_PATH\s*=\s*(.+?)\s*$",
                                     run_script, re.MULTILINE):
                configured.append((f"{step_label}.run", match.group(1).strip().strip("\"'")))
            for toml_match in re.finditer(
                r"cat\s*>\s*config\.toml\s*<<'?TOML'?\n(.*?)\n\s*TOML\b",
                run_script,
                re.DOTALL,
            ):
                parsed = tomllib.loads(toml_match.group(1))
                backend_cfg = parsed.get("backend")
                if isinstance(backend_cfg, dict) and "database_path" in backend_cfg:
                    configured.append((f"{step_label}.config.toml", str(backend_cfg["database_path"])))

    smoke_paths = [value for source, value in configured if source.startswith("deployment-smoke.")]
    assert smoke_paths, "deployment-smoke 必须显式配置 backend.database_path 文件路径"

    for source, value in configured:
        lowered = value.strip().lower()
        assert lowered and lowered not in {".", "..", ":memory:"}, f"{source} 不能配置内存或空数据库路径: {value!r}"
        assert not lowered.startswith("file:") and "mode=memory" not in lowered, (
            f"{source} 不能配置 SQLite URI 或内存数据库: {value!r}"
        )

    smoke_run = "\n".join(step.get("run", "") for step in JOBS["deployment-smoke"]["steps"])
    assert "http://127.0.0.1:8000/chat/sessions" in smoke_run, "deployment-smoke 必须探活 SQLite 查询接口 /chat/sessions"
