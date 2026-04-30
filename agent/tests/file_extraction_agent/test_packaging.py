from __future__ import annotations

import tomllib
from pathlib import Path


def test_pyproject_packages_service_business_subpackages():
    pyproject_path = Path(__file__).resolve().parents[2] / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    packages = pyproject["tool"]["setuptools"]["packages"]
    assert "service" in packages
    assert "service.document_processor" in packages
    assert "service.document_processor.impl" in packages
    assert "service.document_processor.impl.docx" in packages
    assert "service.document_processor.impl.pdf" in packages
    assert "service.file_extraction_agent" in packages
    assert "service.file_extraction_agent.impl" in packages
    assert "service.file_extraction_agent.impl.broad" in packages
    assert "service.file_extraction_agent.impl.resolution" in packages
    assert "service.file_extraction_agent.impl.tools" in packages
    assert "service.route_policy_agent" in packages


def test_tracked_integration_script_imports_service_business_packages():
    agent_root = Path(__file__).resolve().parents[2]
    script_path = (
        agent_root
        / "output"
        / "integration_civilized_dormitory"
        / "run_civilized_dormitory_e2e.py"
    )
    script_source = script_path.read_text(encoding="utf-8")

    assert "from service.document_processor.processor import process" in script_source
    assert "from service.document_processor.types import FileType" in script_source
    assert "from service.file_extraction_agent.processor import extract" in script_source
    assert "from service.file_extraction_agent.schemas import (" in script_source
    assert "agent/service/file_extraction_agent/.env" in script_source
    assert "from document_processor." not in script_source
    assert "from file_extraction_agent." not in script_source
    assert "agent/file_extraction_agent/.env" not in script_source
