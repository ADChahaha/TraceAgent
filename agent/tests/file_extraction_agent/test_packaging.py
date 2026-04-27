from __future__ import annotations

import tomllib
from pathlib import Path


def test_pyproject_packages_file_extraction_agent_impl_subpackage():
    pyproject_path = Path(__file__).resolve().parents[2] / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    packages = pyproject["tool"]["setuptools"]["packages"]
    assert "file_extraction_agent" in packages
    assert "file_extraction_agent.impl" in packages
