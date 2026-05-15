from __future__ import annotations

from langchain_core.messages import AIMessage

from service.file_extraction_agent.impl.html_state import build_graph_state
from service.file_extraction_agent.impl.html_tools import build_tools
from service.file_extraction_agent.impl.resolution_new import _single_tool_call_message, build_resolution_messages
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


def test_resolution_messages_describe_read_judgement_policy_without_tool_manual():
    messages = build_resolution_messages(_state())
    content = "\n\n".join(message.content for message in messages)

    assert "semantic HTML virtual file tree" in content
    assert "Call exactly one tool in each assistant turn" in content
    assert "Never emit multiple or parallel tool calls in one turn" in content
    assert "Wait for that tool result before deciding the next tool call" in content
    assert "reason is a user-visible action explanation" in content
    assert "Every reason must connect the previous action to the next action" in content
    assert "First summarize what the previous action showed" in content
    assert "then state the tool action you are about to take" in content
    assert "After every successful read, the next tool must be bind_evidence or skip_read" in content
    assert "Use bind_evidence when the current read object may support, contradict, or qualify any field" in content
    assert "Use skip_read only when the current read object is irrelevant to every field" in content
    assert "bind_evidence records the current read object as block candidate evidence" in content
    assert "review_evidences expands block candidates into Sxxx/Ixxx/Rxxx inline selectors" in content
    assert "write_field final_evidence must copy inline selectors from review_evidences" in content
    assert "Use path_id locators like [0000.0001]" in content
    assert "Tool-specific navigation and argument rules are provided in each tool description" in content
    assert "tree(path, depth, reason)" not in content
    assert "read(path, offset, limit, reason)" not in content
    assert "tree(path_id, depth, reason)" not in content
    assert "read(path_id, offset, limit, reason)" not in content
    assert "anchors" not in content
    assert "query_table" not in content
    assert "review_field" not in content
    assert "soft plan" not in content.lower()
    assert "record_note" not in content
    assert "overview" not in content


def test_resolution_messages_include_depth_3_initial_tree_with_readable_files():
    messages = build_resolution_messages(_state())
    content = "\n\n".join(message.content for message in messages)

    assert "Initial virtual tree:" in content
    assert "[0000] /" in content
    assert "[0000.0001] company-公司资料/" in content
    assert "[0000.0001.0001] 概况/" in content
    assert "[0000.0001.0001.0001] 公司成立于2020年.md" in content


def test_tool_descriptions_carry_read_judgement_and_review_contracts():
    tools = {getattr(tool, "name", getattr(tool, "__name__", "")): tool for tool in build_tools(_state())}

    assert "Use this for directories" in tools["tree"].description
    assert "Use only path_id values" in tools["tree"].description
    assert "Only read file path_ids ending in .md, .list, or .table" in tools["read"].description
    assert "After a successful read, the next tool must be bind_evidence or skip_read" in tools["read"].description
    assert "current read object" in tools["bind_evidence"].description
    assert "Use bindings=[{field_id}, ...] when the current read object supports multiple fields" in tools["bind_evidence"].description
    assert "Do not pass path_id, sentences, items, or rows" in tools["bind_evidence"].description
    assert "Use this only when the current read object is irrelevant" in tools["skip_read"].description
    assert "review_evidences expands block candidate evidence into inline selectors" in tools["review_evidences"].description
    assert "final_evidence must be copied from review_evidences.evidence" in tools["write_field"].description
    assert "Only null-typed fields or null enum variants may use final_evidence=[]" in tools["submit_result"].description


def test_resolution_messages_expand_enum_variants():
    extraction_input = build_graph_input(
        documents=[
            {
                "filename": "contract.html",
                "html": "<h1>合同</h1><p>接收方不得披露保密信息。</p>",
            }
        ],
        task_spec={
            "fields": [
                {
                    "name": "nda_1_decision",
                    "type": "enum",
                    "required": True,
                    "variants": [
                        {"name": "Entailment", "type": "null"},
                        {"name": "Contradiction", "type": "null"},
                        {"name": "NotMentioned", "type": "null"},
                    ],
                    "description": "判断合同是否支持该假设。",
                }
            ]
        },
    )

    messages = build_resolution_messages(build_graph_state(extraction_input))
    content = "\n\n".join(message.content for message in messages)

    assert "- nda_1_decision: type=enum" in content
    assert "variants=Entailment(null), Contradiction(null), NotMentioned(null)" in content
    assert 'write_field value shape: {"variant": "<variant name>", "value": <payload>}' in content


def test_resolution_graph_exposes_new_tools_only():
    tools = build_tools(_state())
    tool_names = [getattr(tool, "name", getattr(tool, "__name__", "")) for tool in tools]

    assert tool_names == [
        "tree",
        "read",
        "bind_evidence",
        "skip_read",
        "review_evidences",
        "write_field",
        "submit_result",
    ]


def test_resolution_limits_model_to_one_tool_call_per_turn():
    message = AIMessage(
        content="",
        tool_calls=[
            {"id": "call-1", "name": "read", "args": {"path_id": "/a.md"}},
            {"id": "call-2", "name": "read", "args": {"path_id": "/b.md"}},
        ],
    )

    limited = _single_tool_call_message(message)

    assert limited is not message
    assert [call["id"] for call in limited.tool_calls] == ["call-1"]
