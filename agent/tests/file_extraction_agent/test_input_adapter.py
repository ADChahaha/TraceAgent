from __future__ import annotations

import pytest

from service.file_extraction_agent.input_adapter import build_graph_input


def test_build_graph_input_accepts_documents_with_filename_and_html():
    extraction_input = build_graph_input(
        documents=[{"filename": "notice.html", "html": '<p id="p1">正文</p>'}],
        task_spec={"fields": [{"name": "title"}]},
    )

    assert extraction_input.documents[0].filename == "notice.html"
    assert "/001-notice" in extraction_input.document.nodes_by_path


def test_build_graph_input_rejects_missing_documents():
    with pytest.raises(ValueError, match="documents"):
        build_graph_input(documents=[], task_spec={"fields": [{"name": "title"}]})


def test_build_graph_input_rejects_document_without_filename_or_html():
    with pytest.raises(ValueError, match="filename"):
        build_graph_input(
            documents=[{"html": '<p id="p1">正文</p>'}],
            task_spec={"fields": [{"name": "title"}]},
        )
    with pytest.raises(ValueError, match="html"):
        build_graph_input(
            documents=[{"filename": "notice.html", "html": ""}],
            task_spec={"fields": [{"name": "title"}]},
        )


def test_build_graph_input_rejects_missing_task_spec():
    with pytest.raises(ValueError, match="task_spec"):
        build_graph_input(
            documents=[{"filename": "notice.html", "html": '<p id="p1">正文</p>'}],
            task_spec=None,
        )


def test_build_graph_input_rejects_empty_fields():
    with pytest.raises(ValueError, match="fields"):
        build_graph_input(
            documents=[{"filename": "notice.html", "html": '<p id="p1">正文</p>'}],
            task_spec={"fields": []},
        )
