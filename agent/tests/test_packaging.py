"""构建实际 wheel，确认安装包包含解析、资源准备和问答模块。"""

from pathlib import Path
import subprocess
import shutil
import sys
import zipfile


def test_wheel_contains_resource_and_qa_modules(tmp_path):
    source = Path(__file__).resolve().parents[1]
    project = tmp_path / "source"
    project.mkdir()
    for folder in ("service", "routes"):
        shutil.copytree(source / folder, project / folder, ignore=shutil.ignore_patterns("__pycache__"))
    for filename in ("main.py", "pyproject.toml", "README.md"):
        shutil.copy2(source / filename, project / filename)
    result = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "--no-build-isolation", "-w", str(tmp_path)],
        cwd=project, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    with zipfile.ZipFile(next(tmp_path.glob("*.whl"))) as wheel:
        names = set(wheel.namelist())
    assert {
        "routes/document_resources.py", "service/document_resources/resources.py",
        "service/document_resources/model.py", "service/document_resources/documents.py",
        "service/document_processor/docx/docx_processor.py", "service/file_extraction_agent/core/loop.py",
        "service/file_extraction_agent/core/tools/embedding.py",
        "service/file_extraction_agent/core/graph.py", "service/file_extraction_agent/completion_runtime.py",
        "service/file_extraction_agent/core/messages.py", "service/file_extraction_agent/core/model_invocation.py",
        "service/file_extraction_agent/core/executor.py",
    } <= names
    assert "routes/document_processor.py" not in names
    assert not any(name.startswith("service/file_extraction_agent/core/tools/embedding/") for name in names)
