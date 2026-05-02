from __future__ import annotations

import pytest

from service.file_extraction_agent.input_adapter import build_graph_input


def test_build_graph_input_accepts_html_with_existing_ids():
    extraction_input = build_graph_input(
        html='<p id="dp-p-1">正文</p>',
        task_spec={"fields": [{"name": "title"}]},
    )

    assert extraction_input.task_spec.fields[0].name == "title"
    assert "dp-p-1" in extraction_input.document.elements_by_id


def test_build_graph_input_rejects_missing_task_spec():
    with pytest.raises(ValueError, match="task_spec"):
        build_graph_input(html='<p id="dp-p-1">正文</p>', task_spec=None)


def test_build_graph_input_rejects_html_without_required_ids():
    with pytest.raises(ValueError, match="missing id"):
        build_graph_input(
            html="<p>正文</p>",
            task_spec={"fields": [{"name": "title"}]},
        )


def test_build_graph_input_rejects_duplicate_ids():
    with pytest.raises(ValueError, match="duplicate id"):
        build_graph_input(
            html='<p id="dup">一</p><p id="dup">二</p>',
            task_spec={"fields": [{"name": "title"}]},
        )


def test_build_graph_input_rejects_empty_fields():
    with pytest.raises(ValueError, match="fields"):
        build_graph_input(html='<p id="dp-p-1">正文</p>', task_spec={"fields": []})
