from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import AIMessage, AIMessageChunk

from service.file_extraction_agent.impl.html_state import build_graph_state
from service.file_extraction_agent.impl.html_tools import build_tools
from service.file_extraction_agent.impl.resolution_new import (
    build_resolution_graph,
    _invoke_model_message,
    _record_model_message,
    build_resolution_messages,
)
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


def test_resolution_messages_describe_candidate_policy_without_tool_manual():
    messages = build_resolution_messages(_state())
    system_content = messages[0].content
    content = "\n\n".join(message.content for message in messages)

    assert "semantic HTML virtual file tree" in system_content
    assert "Your goal is to extract fields according to task_spec and finally call submit_result" in system_content
    assert "Assistant content is a progress update for a human reviewer, not a tool-call log" in system_content
    assert "Write assistant content only when the latest observation changes what the reviewer understands" in system_content
    assert "Leave assistant content empty for mechanical tree navigation" in system_content
    assert "calling read before seeing the content" in system_content
    assert "routine candidate saves" in system_content
    assert "Summarize useful read results in one natural sentence" in system_content
    assert "Do not use fixed headings such as Read/Finding/Next" in system_content
    assert "Do not narrate tool names" in system_content
    assert "Vary wording and avoid repeating the same sentence shape" in system_content
    assert "Write assistant content in the same language as task_spec" in system_content
    assert "keep quoted source text in the original source language" in system_content
    assert "When a summary depends on consecutive blocks in the same section" in system_content
    assert "cite the whole continuous span instead of only the first block" in system_content
    assert "evidence://range/<start>/<end>" in system_content
    assert "Call exactly one tool in each assistant turn" in system_content
    assert "Never emit multiple or parallel tool calls in one turn" in system_content
    assert "Tool-specific argument rules are provided in the tool descriptions" in system_content
    assert "In assistant content, use evidence:// links for source or path references" in system_content
    assert "When assistant content cites source text, use Markdown evidence links" in system_content
    assert "Do not quote source words in plain quotation marks without an evidence link" in system_content
    assert "Before the first tool call" not in system_content
    assert "Before starting a new reading cluster" not in system_content
    assert "When saving candidate evidence" not in system_content
    assert "Read:" not in system_content
    assert "Saving candidate:" not in system_content
    assert "Review:" not in system_content
    assert "Write:" not in system_content
    assert "Use the current tool's docstring as the note template" not in system_content
    assert "Task fields:" in content


def test_resolution_messages_do_not_inline_initial_tree():
    messages = build_resolution_messages(_state())
    content = "\n\n".join(message.content for message in messages)

    assert "Task fields:" in content
    assert "Initial virtual tree:" not in content
    assert "evidence://0000 /" not in content
    assert "evidence://0001 company-公司资料/" not in content
    assert "evidence://0001.0001 概况/" not in content
    assert "evidence://0001.0001.0001 公司成立于2020年.md" not in content
    assert "Use tree first to inspect the virtual file tree" in content


def test_tool_descriptions_carry_candidate_and_review_contracts():
    tools = {getattr(tool, "name", getattr(tool, "__name__", "")): tool for tool in build_tools(_state())}

    assert "Use this for directories" in tools["tree"].description
    assert "path_id empty for the root" in tools["tree"].description
    assert "evidence://0001 copied" in tools["tree"].description
    assert "Only read file evidence links ending in .md, .list, or .table" in tools["read"].description
    assert "Use evidence links such as evidence://0001.0001.0002" in tools["read"].description
    assert set(tools["read"].args) == {"path_id"}
    assert "count reads consecutive readable blocks" not in tools["read"].description
    assert "count is capped" not in tools["read"].description
    assert "consecutive readable blocks" not in tools["read"].description
    assert "same local semantics" not in tools["read"].description
    assert "Do not always use the maximum count" not in tools["read"].description
    assert "offset" not in tools["read"].description
    assert "limit" not in tools["read"].description
    assert "pagination" not in tools["read"].description
    assert "read does not require an immediate add_candidate_evidence" in tools["read"].description
    assert "Do not narrate the read call before seeing its result" in tools["read"].description
    assert "After a read result is available" in tools["read"].description
    assert "summarize useful source content in the next assistant turn" in tools["read"].description
    assert "Leave routine adjacent reads silent until they form a meaningful chunk" in tools["read"].description
    assert "If that summary depends on consecutive blocks in the same section" in tools["read"].description
    assert "use one evidence://range/<start>/<end> link" in tools["read"].description
    assert "If assistant content mentions source text" in tools["read"].description
    assert "Do not use fixed headings" in tools["read"].description
    assert "Add one readable paragraph/list/table evidence link as block candidate evidence" in tools["add_candidate_evidence"].description
    assert "Use exactly one field_id and one path_id" in tools["add_candidate_evidence"].description
    assert "one paragraph, list, or table block" in tools["add_candidate_evidence"].description
    assert "Routine candidate saves can stay silent" in tools["add_candidate_evidence"].description
    assert "Assistant content is not required for every candidate save" in tools["add_candidate_evidence"].description
    assert "Use content only when the candidate changes the evidence picture" in tools["add_candidate_evidence"].description
    assert "path_ids" not in tools["add_candidate_evidence"].args
    assert "bindings" not in tools["add_candidate_evidence"].args
    assert "bindings=[{field_id, path_ids}, ...]" not in tools["add_candidate_evidence"].description
    assert "binding several fields" not in tools["add_candidate_evidence"].description
    assert "possible or uncertain relevance is enough to add as candidate" in tools["add_candidate_evidence"].description
    assert "Candidate evidence can be broader than final_evidence" in tools["add_candidate_evidence"].description
    assert "final_evidence is selected later after review" in tools["add_candidate_evidence"].description
    assert "include a Markdown evidence link to the same block path_id you are saving" in tools["add_candidate_evidence"].description
    assert "[\"quoted words\"](evidence://0001.0014.0001)" in tools["add_candidate_evidence"].description
    assert "Do not leave source words as plain quoted text" in tools["add_candidate_evidence"].description
    assert "This candidate is not the final field decision" in tools["add_candidate_evidence"].description
    assert "Assistant content is optional for routine candidate additions" not in tools["add_candidate_evidence"].description
    assert "Use content when this candidate addition completes a meaningful candidate-evidence group" not in tools["add_candidate_evidence"].description
    assert "Assistant content is not optional when you call add_candidate_evidence" not in tools["add_candidate_evidence"].description
    assert "Do not pass sentence/item/row inline links" in tools["add_candidate_evidence"].description
    assert "bind_evidence" not in tools["add_candidate_evidence"].description
    assert "review_evidences expands block candidate evidence into inline evidence links" in tools["review_evidences"].description
    assert "Use review_evidences like checking your notes before deciding whether to write or keep reading" in tools["review_evidences"].description
    assert "Use content when review changes evidence sufficiency" in tools["review_evidences"].description
    assert "Routine review checks can stay silent" in tools["review_evidences"].description
    assert "Only write after review makes the evidence sufficient for the field decision" in tools["review_evidences"].description
    assert "write_field does not have to immediately follow review_evidences" in tools["write_field"].description
    assert "Use a recent review snapshot" in tools["write_field"].description
    assert "Field writes are decision checkpoints" in tools["write_field"].description
    assert "Use one natural sentence when a field is written" in tools["write_field"].description
    assert "add_candidate_evidence adds more candidates for this field after review" in tools["write_field"].description
    assert "review again before" in tools["write_field"].description
    assert "final_evidence must copy inline" in tools["write_field"].description
    assert "evidence:// links from review_evidences.evidence" in tools["write_field"].description
    assert "CRITICAL" not in tools["write_field"].description
    assert "Assistant content citations should use Markdown links like [\"short source quote\"](evidence://0001.0014.0001/S002)" in tools["write_field"].description
    assert "For non-empty final_evidence, assistant content must include a short quote from reviewed evidence_texts" in tools["write_field"].description
    assert "and a Markdown evidence link to either the inline selector or its paragraph/list/table block" in tools["write_field"].description
    assert "explain why the linked text supports the field decision" in tools["write_field"].description
    assert "Block-level evidence links are acceptable in assistant content when they are clearer" in tools["write_field"].description
    assert "Quote the source words as the link label when possible" in tools["write_field"].description
    assert "Tool arguments and final_evidence must use evidence:// links" in tools["write_field"].description
    assert "BAD:" not in tools["write_field"].description
    assert "GOOD:" not in tools["write_field"].description
    assert "(short evidence description)[path_id#selector]" not in tools["write_field"].description
    assert "frontend display label" not in tools["write_field"].description
    assert "reason field" not in tools["write_field"].description
    assert "whose target matches final_evidence" not in tools["write_field"].description
    assert "[path_id#S002,S003]" not in tools["write_field"].description
    assert "classification standard" not in tools["write_field"].description
    assert "semantic or legal equivalents" not in tools["write_field"].description
    assert "Only null-typed fields or null enum variants may use final_evidence=[]" in tools["submit_result"].description
    fixed_headings = [
        "Read:",
        "Finding:",
        "Saving candidate:",
        "Why relevant:",
        "Review:",
        "Sufficiency:",
        "Write:",
        "Why supported:",
        "Next:",
    ]
    for tool in tools.values():
        assert "reason" not in tool.args
        assert "[0000" not in tool.description
        assert "bare path_id" not in tool.description
        for fixed_heading in fixed_headings:
            assert fixed_heading not in tool.description


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
        "add_candidate_evidence",
        "review_evidences",
        "write_field",
        "submit_result",
    ]


def test_resolution_graph_executes_only_first_model_tool_call_per_turn():
    state = _state()
    path_id = next(
        state.document.path_id(path)
        for path, node in state.document.nodes_by_path.items()
        if node.kind == "paragraph"
    )

    class MultiToolModel:
        def __init__(self):
            self.calls = 0

        def bind_tools(self, tools, **kwargs):
            assert kwargs == {"parallel_tool_calls": False}
            return self

        def invoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(
                    content="I should inspect the root and read the visible paragraph.",
                    tool_calls=[
                        {"id": "call-1", "name": "tree", "args": {"path_id": "evidence://0000", "depth": 1}},
                        {"id": "call-2", "name": "read", "args": {"path_id": f"evidence://{path_id}"}},
                    ],
                )
            return AIMessage(content="", tool_calls=[])

    graph = build_resolution_graph(MultiToolModel(), build_tools(state), state)

    list(graph.stream({"messages": build_resolution_messages(state)}, config={"recursion_limit": 8}))

    model_events = [event for event in state.events if event.get("type") == "model_message"]
    assert [action["tool_name"] for action in state.actions] == ["tree"]
    assert model_events[0]["tool_call_count"] == 1
    assert [call["name"] for call in model_events[0]["tool_calls"]] == ["tree"]


def test_resolution_uses_responses_api_stream_and_merges_content_with_tool_calls():
    class StreamingModel:
        def __init__(self):
            self.streamed = False
            self.invoked = False

        def stream(self, messages):
            self.streamed = True
            assert messages == ["messages"]
            yield AIMessageChunk(content=[{"type": "text", "text": "I will ", "index": 0}])
            yield AIMessageChunk(content=[{"type": "text", "text": "inspect root.", "index": 0}])
            yield AIMessageChunk(
                content=[
                    {
                        "type": "function_call",
                        "name": "tree",
                        "arguments": "",
                        "call_id": "call-1",
                        "id": "fc-1",
                        "index": 1,
                    }
                ],
                tool_call_chunks=[
                    {
                        "type": "tool_call_chunk",
                        "name": "tree",
                        "args": "",
                        "id": "call-1",
                        "index": 1,
                    }
                ],
            )
            yield AIMessageChunk(
                content=[{"type": "function_call", "arguments": '{"path_id":"evidence://0000"', "index": 1}],
                tool_call_chunks=[
                    {"type": "tool_call_chunk", "args": '{"path_id":"evidence://0000"', "index": 1}
                ],
            )
            yield AIMessageChunk(
                content=[{"type": "function_call", "arguments": ',"depth":3}', "index": 1}],
                tool_call_chunks=[
                    {"type": "tool_call_chunk", "args": ',"depth":3}', "index": 1}
                ],
            )

        def invoke(self, messages):
            self.invoked = True
            raise AssertionError("Responses API stream should be used before invoke fallback")

    model = StreamingModel()

    message = _invoke_model_message(model, ["messages"])

    assert model.streamed is True
    assert model.invoked is False
    assert isinstance(message, AIMessage)
    assert message.content == [
        {"type": "text", "text": "I will inspect root.", "index": 0},
        {
            "type": "function_call",
            "name": "tree",
            "arguments": '{"path_id":"evidence://0000","depth":3}',
            "call_id": "call-1",
            "id": "fc-1",
            "index": 1,
        },
    ]
    assert message.tool_calls == [
        {
            "name": "tree",
            "args": {"path_id": "evidence://0000", "depth": 3},
            "id": "call-1",
            "type": "tool_call",
        }
    ]


def test_resolution_falls_back_from_responses_stream_to_chat_stream_then_invoke():
    calls = []

    class FailingStreamModel:
        def __init__(self, name):
            self.name = name

        def stream(self, messages):
            calls.append(f"{self.name}.stream")
            raise RuntimeError(f"{self.name} failed")

    class InvokeModel:
        def __init__(self, name):
            self.name = name

        def invoke(self, messages):
            calls.append(f"{self.name}.invoke")
            return AIMessage(
                content="fallback invoke worked",
                tool_calls=[
                    {
                        "id": "call-1",
                        "name": "tree",
                        "args": {"path_id": "evidence://0000", "depth": 1},
                    }
                ],
            )

    class NeverCalledModel:
        def invoke(self, messages):
            raise AssertionError("later fallback should not be called")

    class FallbackModel:
        def model_call_attempts(self):
            return [
                SimpleNamespace(name="responses_stream", model=FailingStreamModel("responses"), use_stream=True),
                SimpleNamespace(name="chat_completions_stream", model=FailingStreamModel("chat"), use_stream=True),
                SimpleNamespace(name="responses_invoke", model=InvokeModel("responses"), use_stream=False),
                SimpleNamespace(name="chat_completions_invoke", model=NeverCalledModel(), use_stream=False),
            ]

    message = _invoke_model_message(FallbackModel(), ["messages"])

    assert calls == ["responses.stream", "chat.stream", "responses.invoke"]
    assert message.content == "fallback invoke worked"
    assert message.tool_calls[0]["name"] == "tree"


def test_resolution_records_text_from_responses_api_content_blocks():
    state = _state()
    message = AIMessage(
        content=[
            {"type": "reasoning", "summary": []},
            {"type": "text", "text": "I will inspect root. "},
            {"type": "function_call", "name": "tree", "arguments": '{"path_id":"evidence://0000"}'},
        ],
        tool_calls=[
            {
                "id": "call-1",
                "name": "tree",
                "args": {"path_id": "evidence://0000", "depth": 3},
            }
        ],
    )

    _record_model_message(state, message)

    assert state.current_model_content == "I will inspect root. "
    assert state.events[-1]["content"] == "I will inspect root. "


def test_resolution_records_model_message_content_and_tool_calls_without_reasoning():
    state = _state()
    message = AIMessage(
        content="I will inspect the root tree while calling a tool.",
        additional_kwargs={"reasoning_content": "hidden reasoning must not be persisted"},
        tool_calls=[
            {
                "id": "call-1",
                "name": "tree",
                "args": {"path_id": "evidence://0000", "depth": 3},
            }
        ],
    )

    _record_model_message(state, message)

    event = state.events[-1]
    assert event["seq"] == 1
    assert event["type"] == "model_message"
    assert event["content"] == "I will inspect the root tree while calling a tool."
    assert event["tool_call_count"] == 1
    assert event["tool_calls"] == [
        {
            "id": "call-1",
            "name": "tree",
            "args": {"path_id": "evidence://0000", "depth": 3},
        }
    ]
    assert "reasoning_content" not in event


def test_tool_actions_do_not_store_model_message_content_as_reason():
    state = _state()
    tools = {getattr(tool, "name", getattr(tool, "__name__", "")): tool for tool in build_tools(state)}
    _record_model_message(
        state,
        AIMessage(
            content="The initial tree is visible, so I will inspect the root directory.",
            tool_calls=[
                {
                    "id": "call-1",
                    "name": "tree",
                    "args": {"path_id": "evidence://0000", "depth": 1},
                }
            ],
        ),
    )

    result = tools["tree"].invoke({"path_id": "evidence://0000", "depth": 1})

    assert result["ok"] is True
    action = state.actions[-1]
    assert action["tool_name"] == "tree"
    assert action["args"] == {"path_id": "evidence://0000", "depth": 1}
    assert "reason" not in action
    completed = state.events[-1]
    assert completed["type"] == "tool_completed"
    assert "reason" not in completed


def test_tool_actions_do_not_write_empty_reason():
    state = _state()
    tools = {getattr(tool, "name", getattr(tool, "__name__", "")): tool for tool in build_tools(state)}
    _record_model_message(
        state,
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "call-1",
                    "name": "tree",
                    "args": {"path_id": "evidence://0000", "depth": 1},
                }
            ],
        ),
    )

    result = tools["tree"].invoke({"path_id": "evidence://0000", "depth": 1})

    assert result["ok"] is True
    action = state.actions[-1]
    assert action["tool_name"] == "tree"
    assert "reason" not in action
    completed = state.events[-1]
    assert completed["type"] == "tool_completed"
    assert "reason" not in completed
