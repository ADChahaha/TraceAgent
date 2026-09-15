"""验证 document service wheel 包含文档业务而不包含 agent 问答代码。"""

from pathlib import Path
import shutil
import subprocess
import sys
import zipfile


def test_wheel_contains_document_service_only(tmp_path):
    source = Path(__file__).resolve().parents[1]
    project = tmp_path / "source"
    project.mkdir()
    shutil.copytree(source, project / "document_service")
    shutil.copy2(source / "pyproject.toml", project / "pyproject.toml")
    shutil.copy2(source / "README.md", project / "README.md")

    result = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "--no-build-isolation", "-w", str(tmp_path)],
        cwd=project, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    with zipfile.ZipFile(next(tmp_path.glob("*.whl"))) as wheel:
        names = set(wheel.namelist())
        assert "document_service/main.py" in names
        assert "document_service/document_processor/processor.py" in names
        assert "document_service/document_resources/resources.py" in names
        assert not any(name.startswith("service/") for name in names)
        assert not any(name.startswith("routes/") for name in names)
