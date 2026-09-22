"""检查 CI 安装依赖与仓库服务边界一致，并实际执行 OCR 模块导入。"""

import ast
import os
from pathlib import Path
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
