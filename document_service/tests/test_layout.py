"""验证 document service 的目录边界和独立入口。"""

from pathlib import Path
import subprocess
import sys


def test_document_service_owns_processing_and_resource_modules():
    root = Path(__file__).resolve().parents[1]
    repository = root.parent

    assert (root / "main.py").is_file()
    assert (root / "routes.py").is_file()
    assert (root / "document_processor" / "processor.py").is_file()
    assert (root / "document_resources" / "resources.py").is_file()
    assert not (repository / "agent" / "service" / "document_processor").exists()
    assert not (repository / "agent" / "service" / "document_resources").exists()


def test_document_service_imports_without_agent_business_package():
    repository = Path(__file__).resolve().parents[2]
    result = subprocess.run([
        sys.executable,
        "-c",
        "import sys; import document_service.main; assert 'service.file_extraction_agent' not in sys.modules",
    ], cwd=repository, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
