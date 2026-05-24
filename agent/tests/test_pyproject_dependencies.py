from __future__ import annotations

import re
import tomllib
from pathlib import Path


PYPROJECT_PATH = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_agent_pyproject_declares_direct_runtime_dependencies():
    pyproject = _load_pyproject()
    dependency_names = _dependency_names(pyproject["project"]["dependencies"])

    assert {"langchain-core", "pydantic", "starlette"} <= dependency_names


def test_agent_pyproject_declares_direct_test_dependencies():
    pyproject = _load_pyproject()
    dev_dependency_names = _dependency_names(pyproject["project"]["optional-dependencies"]["dev"])

    assert {"httpx", "pytest"} <= dev_dependency_names


def _load_pyproject() -> dict:
    return tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))


def _dependency_names(dependencies: list[str]) -> set[str]:
    return {
        re.split(r"\s*(?:\[|==|~=|!=|<=|>=|<|>|;)", dependency, maxsplit=1)[0].lower()
        for dependency in dependencies
    }
