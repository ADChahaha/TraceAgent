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
    assert "service.route_policy_agent" in packages
