from __future__ import annotations

import pytest

from service.file_extraction_agent.input_adapter import build_completion_input


def test_build_completion_input_accepts_documents_and_append_only_messages(tmp_path):
    completion_input = build_completion_input(
        completion_id="cmp_123",
        documents=[{"filename": "notice.html", "html": '<p id="p1">正文</p>'}],
        messages=[{"role": "user", "content": "这份文件说了什么？"}],
        workspace_root=tmp_path,
    )

    assert completion_input.completion_id == "cmp_123"
    assert completion_input.documents[0].filename == "notice.html"
    assert completion_input.messages[0].content == "这份文件说了什么？"
    assert not hasattr(completion_input, "memory")
    assert completion_input.document.root == tmp_path / "cmp_123"


def test_build_completion_input_rejects_memory_argument(tmp_path):
    with pytest.raises(TypeError, match="memory"):
        build_completion_input(
            completion_id="cmp_123",
            documents=[{"filename": "notice.html", "html": '<p id="p1">正文</p>'}],
            messages=[{"role": "user", "content": "问题"}],
            memory={"prior_answers": ["会破坏 append-only prompt cache"]},
            workspace_root=tmp_path,
        )


def test_build_completion_input_rejects_missing_documents_or_messages(tmp_path):
    with pytest.raises(ValueError, match="documents"):
        build_completion_input(
            completion_id="cmp_123",
            documents=[],
            messages=[{"role": "user", "content": "问题"}],
            workspace_root=tmp_path,
        )
    with pytest.raises(ValueError, match="messages"):
        build_completion_input(
            completion_id="cmp_123",
            documents=[{"filename": "notice.html", "html": '<p id="p1">正文</p>'}],
            messages=[],
            workspace_root=tmp_path,
        )


def test_build_completion_input_rejects_document_without_filename_or_html(tmp_path):
    with pytest.raises(ValueError, match="filename"):
        build_completion_input(
            completion_id="cmp_123",
            documents=[{"html": '<p id="p1">正文</p>'}],
            messages=[{"role": "user", "content": "问题"}],
            workspace_root=tmp_path,
        )
    with pytest.raises(ValueError, match="html"):
        build_completion_input(
            completion_id="cmp_123",
            documents=[{"filename": "notice.html", "html": ""}],
            messages=[{"role": "user", "content": "问题"}],
            workspace_root=tmp_path,
        )


def test_build_completion_input_requires_completion_id(tmp_path):
    with pytest.raises(ValueError, match="completion_id"):
        build_completion_input(
            completion_id="",
            documents=[{"filename": "notice.html", "html": '<p id="p1">正文</p>'}],
            messages=[{"role": "user", "content": "问题"}],
            workspace_root=tmp_path,
        )
