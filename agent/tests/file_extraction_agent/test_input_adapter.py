from __future__ import annotations

import pytest

from service.file_extraction_agent.input_adapter import build_completion_input


def test_build_completion_input_accepts_documents_messages_and_memory():
    completion_input = build_completion_input(
        completion_id="cmp_123",
        documents=[{"filename": "notice.html", "html": '<p id="p1">正文</p>'}],
        messages=[{"role": "user", "content": "这份文件说了什么？"}],
        memory={"evidence_notes": [{"locator": "evidence://0001.0000.0001", "note": "正文"}]},
    )

    assert completion_input.completion_id == "cmp_123"
    assert completion_input.documents[0].filename == "notice.html"
    assert completion_input.messages[0].content == "这份文件说了什么？"
    assert completion_input.memory.evidence_notes[0]["note"] == "正文"
    assert "/001-notice" in completion_input.document.nodes_by_path


def test_build_completion_input_rejects_missing_documents_or_messages():
    with pytest.raises(ValueError, match="documents"):
        build_completion_input(
            completion_id="cmp_123",
            documents=[],
            messages=[{"role": "user", "content": "问题"}],
        )
    with pytest.raises(ValueError, match="messages"):
        build_completion_input(
            completion_id="cmp_123",
            documents=[{"filename": "notice.html", "html": '<p id="p1">正文</p>'}],
            messages=[],
        )


def test_build_completion_input_rejects_document_without_filename_or_html():
    with pytest.raises(ValueError, match="filename"):
        build_completion_input(
            completion_id="cmp_123",
            documents=[{"html": '<p id="p1">正文</p>'}],
            messages=[{"role": "user", "content": "问题"}],
        )
    with pytest.raises(ValueError, match="html"):
        build_completion_input(
            completion_id="cmp_123",
            documents=[{"filename": "notice.html", "html": ""}],
            messages=[{"role": "user", "content": "问题"}],
        )


def test_build_completion_input_requires_completion_id():
    with pytest.raises(ValueError, match="completion_id"):
        build_completion_input(
            completion_id="",
            documents=[{"filename": "notice.html", "html": '<p id="p1">正文</p>'}],
            messages=[{"role": "user", "content": "问题"}],
        )
