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


def test_resolution_messages_describe_extraction_policy_without_tool_manual():
    messages = build_resolution_messages(_state())
    content = "\n\n".join(message.content for message in messages)

    assert "semantic HTML virtual file tree" in content
    assert "reason is a user-visible action explanation" in content
    assert "Tool-specific navigation and argument rules are provided in each tool description" in content
    assert "as soon as you see text, list items, or table rows that you think may be evidence for a field" in content
    assert "call bind_evidence immediately" in content
    assert "Do not wait until the field value or enum decision is final before binding evidence" in content
    assert "If a field has any bound candidate evidence, call review_field for that field before write_field" in content
    assert "Do not call review_field for fields that have no bound candidate evidence" in content
    assert "write_field submits a field value with final_evidence" in content
    assert "final_evidence should include only selectors that are genuinely useful for the submitted value" in content
    assert "drop merely topical, background, duplicate, or weakly related candidate evidence" in content
    assert "Only null-typed fields or null enum variants may submit final_evidence=[]" in content
    assert "submit_result requires non-empty final_evidence" in content
    assert "tree(path, depth, reason)" not in content
    assert "read(path, offset, limit, reason)" not in content
    assert "query_table(path, sql, offset, limit, reason)" not in content
    assert "Use read to inspect .md/.list/.table files" not in content
    assert "once the value or enum decision is ready" not in content
    assert "maximum number of reads" not in content.lower()
    assert "read budget" not in content.lower()
    assert "Do not create or update a plan" not in content
    assert "old block-reading or field-finalization concepts" not in content
    assert "update_soft_plan" not in content
    assert "soft plan" not in content.lower()
    assert "record_note" not in content
    assert "overview" not in content


def test_tool_descriptions_carry_navigation_and_evidence_contracts():
    tools = {getattr(tool, "name", getattr(tool, "__name__", "")): tool for tool in build_tools(_state())}

    assert "Use this for directories" in tools["tree"].description
    assert "Directory paths are shown with a trailing slash" in tools["tree"].description
    assert "Only read paths ending in .md, .list, or .table" in tools["read"].description
    assert "Never call read on document or section directories" in tools["read"].description
    assert "If tree shows a path ending with /, call tree on that directory first" in tools["read"].description
    assert "Only call this for paragraph .md files" in tools["anchors"].description
    assert "Only call this for .table paths" in tools["query_table"].description
    assert "{path, sentences}" in tools["bind_evidence"].description
    assert "Call review_field before write_field" in tools["review_field"].description
    assert "final_evidence must be selected from bound candidate evidence" in tools["write_field"].description
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
        "anchors",
        "query_table",
        "bind_evidence",
        "review_field",
        "write_field",
        "submit_result",
    ]
