from __future__ import annotations

from service.file_extraction_agent.impl.html_state import build_graph_state
from service.file_extraction_agent.impl.html_tools import build_tools
from service.file_extraction_agent.impl.resolution_new import build_resolution_messages
from service.file_extraction_agent.input_adapter import build_graph_input


def _state():
    extraction_input = build_graph_input(
        documents=[
            {
                "filename": "company.html",
                "html": """
                <h1 id="title">公司资料</h1>
                <h2 id="summary">概况</h2>
                <p id="p1">公司成立于2020年。</p>
                """,
            }
        ],
        task_spec={"fields": [{"name": "founded_year", "type": "number", "required": True}]},
    )
    return build_graph_state(extraction_input)


def test_resolution_messages_describe_virtual_tree_tools_without_plan():
    messages = build_resolution_messages(_state())
    content = "\n\n".join(message.content for message in messages)

    assert "semantic HTML virtual file tree" in content
    assert "tree(path, depth, reason)" in content
    assert "read(path, offset, limit, reason)" in content
    assert "anchors(path, reason)" in content
    assert "query_table(path, sql, offset, limit, reason)" in content
    assert "write_field(field_id, value, evidence, status, reason)" in content
    assert "submit_result(reason)" in content
    assert "reason is a user-visible action explanation" in content
    assert "Use evidence selectors" in content
    assert "Once you have enough evidence for a field" in content
    assert "write_field for that field" in content
    assert "before continuing to unrelated fields" in content
    assert "maximum number of reads" not in content.lower()
    assert "read budget" not in content.lower()
    assert "update_soft_plan" not in content
    assert "soft plan" not in content.lower()
    assert "record_note" not in content
    assert "overview" not in content


def test_resolution_graph_exposes_new_tools_only():
    tools = build_tools(_state())
    tool_names = [getattr(tool, "name", getattr(tool, "__name__", "")) for tool in tools]

    assert tool_names == [
        "tree",
        "read",
        "anchors",
        "query_table",
        "write_field",
        "submit_result",
    ]
