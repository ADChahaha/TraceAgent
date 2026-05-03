import json

import pytest

from service.document_processor.mineru_converter import (
    MinerUConversionError,
    find_content_list_v2,
    resolve_mineru_executable,
    resolve_mineru_lang,
)


def test_find_content_list_v2_returns_nested_artifact(tmp_path):
    artifact = tmp_path / "doc" / "auto" / "sample_content_list_v2.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text(json.dumps([]), encoding="utf-8")

    assert find_content_list_v2(tmp_path) == artifact


def test_resolve_mineru_executable_uses_env(monkeypatch):
    monkeypatch.setenv("MINERU_BIN", "/tmp/mineru")

    assert resolve_mineru_executable() == "/tmp/mineru"


def test_resolve_mineru_executable_errors_when_missing(monkeypatch):
    monkeypatch.delenv("MINERU_BIN", raising=False)
    monkeypatch.setattr("service.document_processor.mineru_converter.shutil.which", lambda name: None)

    with pytest.raises(MinerUConversionError, match="MinerU executable not found"):
        resolve_mineru_executable()


def test_resolve_mineru_lang_uses_env(monkeypatch):
    monkeypatch.setenv("DOCUMENT_PROCESSOR_MINERU_LANG", "ch")

    assert resolve_mineru_lang() == "ch"


def test_resolve_mineru_lang_defaults_to_japan(monkeypatch):
    monkeypatch.delenv("DOCUMENT_PROCESSOR_MINERU_LANG", raising=False)

    assert resolve_mineru_lang() == "japan"
