from __future__ import annotations

import random
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from service.file_extraction_agent.impl import resolution_new as resolution_module
from service.file_extraction_agent.impl.html_state import build_graph_state
from service.file_extraction_agent.impl.html_tools import build_tools
from service.file_extraction_agent.impl.resolution_new import (
    _invoke_model_message,
    _record_model_message,
    build_resolution_graph,
    build_resolution_messages,
)
from service.file_extraction_agent.input_adapter import build_completion_input


def _state():
    completion_input = build_completion_input(
        completion_id="cmp_123",
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
        messages=[
            {"role": "user", "content": "公司什么时候成立？"},
        ],
    )
    return build_graph_state(completion_input)


def test_resolution_messages_describe_qa_investigation_not_field_extraction():
    messages = build_resolution_messages(_state())
    system_content = messages[0].content
    human_content = messages[1].content

    assert len(messages) == 2
    assert "document" in system_content.lower()
    assert "answer" in system_content.lower()
    assert "evidence" in system_content.lower()
    assert "Do not put evidence links inline in the final answer body" in system_content
    assert "Append a final Sources section" in system_content
    assert "[1] [short label](evidence://...)" in system_content
    assert "task_spec" not in system_content
    assert "write_field" not in system_content
    assert "submit_result" not in system_content
    assert "公司什么时候成立？" in human_content
    assert "Context from prior turns" not in system_content
    assert "Investigate the documents" not in human_content


def test_resolution_prompt_allows_direct_answers_without_forced_document_search():
    messages = build_resolution_messages(_state())
    system_content = messages[0].content

    assert "Answer directly when the question can be answered from conversation context" in system_content
    assert "general assistant identity/capability" in system_content
    assert "Use document tools when the user asks about document content" in system_content
    assert "When using document tools, show a brief investigation trace" in system_content
    assert "Do not inspect unrelated documents just to satisfy symmetry" in system_content
    assert "Show your thought process" not in system_content
    assert "One tool per turn" not in system_content


def test_resolution_messages_preserve_openai_tool_history():
    completion_input = build_completion_input(
        completion_id="cmp_123",
        documents=[
            {
                "filename": "company.html",
                "html": '<h1 id="title">公司资料</h1><p id="p1">公司成立于2020年。</p>',
            }
        ],
        messages=[
            {"role": "user", "content": "查成立时间"},
            {
                "role": "assistant",
                "content": "我先读公司概况。",
                "tool_calls": [
                    {
                        "id": "call_read_company",
                        "type": "function",
                        "function": {
                            "name": "read",
                            "arguments": "{\"locator\":\"evidence://0001.0001.0001\"}",
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_read_company",
                "name": "read",
                "content": "{\"ok\":true,\"text\":\"公司成立于2020年。\"}",
            },
            {"role": "user", "content": "所以是哪一年？"},
        ],
    )
    messages = build_resolution_messages(build_graph_state(completion_input))

    assert messages[1].type == "human"
    assert messages[2].type == "ai"
    assert messages[2].tool_calls[0]["id"] == "call_read_company"
    assert isinstance(messages[3], ToolMessage)
    assert messages[3].tool_call_id == "call_read_company"
    assert messages[4].type == "human"
    assert len(messages) == 5
    assert messages[-1].content == "所以是哪一年？"
    assert "Investigate the documents" not in messages[-1].content


def test_resolution_graph_preserves_parallel_tool_calls():
    state = _state()
    paragraph_path_id = "0001.0001.0001"

    class MultiToolModel:
        def __init__(self):
            self.calls = 0
            self.bind_kwargs = None

        def bind_tools(self, tools, **kwargs):
            del tools
            self.bind_kwargs = kwargs
            return self

        def stream(self, messages):
            del messages
            self.calls += 1
            if self.calls > 1:
                yield AIMessageChunk(
                    content="我已经看过结构。",
                    response_metadata={"finish_reason": "stop"},
                )
                return
            yield AIMessageChunk(
                content="我先看结构。",
                tool_call_chunks=[
                    {
                        "type": "tool_call_chunk",
                        "name": "tree",
                        "args": '{"path_id":"","depth":1}',
                        "id": "call-1",
                        "index": 0,
                    },
                    {
                        "type": "tool_call_chunk",
                        "name": "read",
                        "args": f'{{"locator":"evidence://{paragraph_path_id}"}}',
                        "id": "call-2",
                        "index": 1,
                    },
                ],
            )

    model = MultiToolModel()
    graph = build_resolution_graph(model, build_tools(state), state)

    list(graph.stream({"messages": build_resolution_messages(state)}, config={"recursion_limit": 4}))

    model_events = [event for event in state.events if event.get("type") == "model_message"]
    assert model.bind_kwargs == {}
    assert [action["tool_name"] for action in state.actions] == ["tree", "read"]
    assert model_events[0]["tool_call_count"] == 2
    assert [call["name"] for call in model_events[0]["tool_calls"]] == ["tree", "read"]


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
                content="",
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
                content="",
                tool_call_chunks=[
                    {"type": "tool_call_chunk", "args": '{"path_id":""', "index": 1}
                ],
            )
            yield AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {"type": "tool_call_chunk", "args": ',"depth":3}', "index": 1}
                ],
            )

        def invoke(self, messages):
            self.invoked = True
            raise AssertionError("stream should be used before invoke fallback")

    model = StreamingModel()

    message = _invoke_model_message(model, ["messages"])

    assert model.streamed is True
    assert model.invoked is False
    assert isinstance(message, AIMessage)
    assert message.content == [{"type": "text", "text": "I will inspect root.", "index": 0}]
    assert message.tool_calls == [
        {
            "name": "tree",
            "args": {"path_id": "", "depth": 3},
            "id": "call-1",
            "type": "tool_call",
        }
    ]


def test_resolution_falls_back_from_stream_to_invoke_within_configured_transport():
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
                        "args": {"path_id": "", "depth": 1},
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
                SimpleNamespace(name="responses_invoke", model=InvokeModel("responses"), use_stream=False),
                SimpleNamespace(name="chat_completions_invoke", model=NeverCalledModel(), use_stream=False),
            ]

    message = _invoke_model_message(FallbackModel(), ["messages"])

    assert calls == ["responses.stream", "responses.invoke"]
    assert message.content == "fallback invoke worked"
    assert message.tool_calls[0]["name"] == "tree"


def test_resolution_uses_ethernet_backoff_between_failed_provider_attempts(monkeypatch):
    calls = []
    sleeps = []

    class FailingStreamModel:
        def __init__(self, name):
            self.name = name

        def stream(self, messages):
            calls.append(f"{self.name}.stream")
            raise TimeoutError(f"{self.name} timeout")

    class SuccessfulInvokeModel:
        def invoke(self, messages):
            calls.append("invoke")
            return AIMessage(
                content="fallback invoke worked",
                tool_calls=[
                    {
                        "id": "call-1",
                        "name": "tree",
                        "args": {"path_id": "", "depth": 1},
                    }
                ],
            )

    class FallbackModel:
        def model_call_attempts(self):
            return [
                SimpleNamespace(name="responses_stream", model=FailingStreamModel("responses"), use_stream=True),
                SimpleNamespace(name="chat_completions_stream", model=FailingStreamModel("chat"), use_stream=True),
                SimpleNamespace(name="responses_invoke", model=SuccessfulInvokeModel(), use_stream=False),
            ]

    monkeypatch.setattr(resolution_module.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(random, "randint", lambda lower, upper: upper)
    monkeypatch.setattr(resolution_module, "PROVIDER_BACKOFF_SLOT_SECONDS", 0.01)

    message = _invoke_model_message(FallbackModel(), ["messages"])

    assert calls == ["responses.stream", "chat.stream", "invoke"]
    assert sleeps == [0.01, 0.03]
    assert message.content == "fallback invoke worked"


def test_resolution_stops_after_provider_attempt_limit(monkeypatch):
    class FailingStreamModel:
        def stream(self, messages):
            del messages
            raise TimeoutError("provider timeout")

    class FallbackModel:
        def model_call_attempts(self):
            return [
                SimpleNamespace(name=f"attempt_{index}", model=FailingStreamModel(), use_stream=True)
                for index in range(7)
            ]

    monkeypatch.setattr(resolution_module.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(random, "randint", lambda lower, upper: lower)

    with pytest.raises(RuntimeError) as exc:
        _invoke_model_message(FallbackModel(), ["messages"])

    message = str(exc.value)
    assert "attempt_0" in message
    assert "attempt_4" in message
    assert "attempt_5" not in message


def test_resolution_records_text_from_responses_api_content_blocks():
    state = _state()
    message = AIMessage(
        content=[
            {"type": "reasoning", "summary": []},
            {"type": "text", "text": "I will inspect root. "},
            {"type": "function_call", "name": "tree", "arguments": '{"path_id":""}'},
        ],
        tool_calls=[
            {
                "id": "call-1",
                "name": "tree",
                "args": {"path_id": "", "depth": 3},
            }
        ],
    )

    _record_model_message(state, message)

    assert state.current_model_content == "I will inspect root. "
    assert state.events[-1]["content"] == "I will inspect root. "




def test_resolution_retries_transport_when_provider_stop_signal_requires_missing_tool_calls():
    calls = []

    class IncompleteToolCallStreamModel:
        def stream(self, messages):
            calls.append("responses.stream")
            assert messages == ["messages"]
            yield AIMessageChunk(
                content="我会先看文档结构，再决定下一步。",
                response_metadata={"finish_reason": "tool_calls"},
            )

    class CompleteToolCallInvokeModel:
        def invoke(self, messages):
            calls.append("responses.invoke")
            assert messages == ["messages"]
            return AIMessage(
                content="我先看结构。",
                tool_calls=[
                    {
                        "id": "call-1",
                        "name": "tree",
                        "args": {"path_id": "", "depth": 3},
                    }
                ],
                response_metadata={"finish_reason": "tool_calls"},
            )

    class FallbackModel:
        def model_call_attempts(self):
            return [
                SimpleNamespace(name="responses_stream", model=IncompleteToolCallStreamModel(), use_stream=True),
                SimpleNamespace(name="responses_invoke", model=CompleteToolCallInvokeModel(), use_stream=False),
            ]

    message = _invoke_model_message(FallbackModel(), ["messages"])

    assert calls == ["responses.stream", "responses.invoke"]
    assert message.content == "我先看结构。"
    assert message.tool_calls[0]["name"] == "tree"


def test_resolution_accepts_terminal_stop_message_without_tool_calls():
    class FinalAnswerModel:
        def stream(self, messages):
            del messages
            yield AIMessageChunk(
                content="最终答案。",
                response_metadata={"finish_reason": "stop"},
            )

    message = _invoke_model_message(FinalAnswerModel(), ["messages"])

    assert message.content == "最终答案。"
    assert message.tool_calls == []


def test_resolution_records_terminal_stop_message_as_final_answer():
    state = _state()
    message = AIMessage(
        content="最终答案。",
        response_metadata={"finish_reason": "stop"},
    )

    _record_model_message(state, message)

    assert state.events[-1]["content"] == "最终答案。"
    assert state.events[-1]["is_final"] is True
    assert state.events[-1]["stop_signal"] == "stop"


def test_resolution_rejects_plan_only_message_without_terminal_stop_signal():
    class PlanOnlyModel:
        def stream(self, messages):
            del messages
            yield AIMessageChunk(content="我会先在同一份入试要项里查相关依据。")

    class FallbackModel:
        def model_call_attempts(self):
            return [
                SimpleNamespace(name="responses_stream", model=PlanOnlyModel(), use_stream=True),
            ]

    try:
        _invoke_model_message(FallbackModel(), ["messages"])
    except RuntimeError as exc:
        assert "terminal stop signal" in str(exc)
    else:
        raise AssertionError("plan-only message without terminal stop signal should fail")


def test_resolution_records_model_message_content_and_tool_calls_without_reasoning():
    state = _state()
    message = AIMessage(
        content="I will inspect the root tree while calling a tool.",
        additional_kwargs={"reasoning_content": "hidden reasoning must not be persisted"},
        tool_calls=[
            {
                "id": "call-1",
                "name": "tree",
                "args": {"path_id": "", "depth": 3},
            }
        ],
    )

    _record_model_message(state, message)

    assert state.events[-1] == {
        "seq": 1,
        "type": "model_message",
        "content": "I will inspect the root tree while calling a tool.",
        "tool_call_count": 1,
        "tool_calls": [{"id": "call-1", "name": "tree", "args": {"path_id": "", "depth": 3}}],
        "is_final": False,
    }
