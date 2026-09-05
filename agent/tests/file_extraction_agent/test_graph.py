from __future__ import annotations

from unittest.mock import Mock

import pytest
from langchain_core.messages import ToolMessage
from service.file_extraction_agent import manager as manager_module

from langchain_core.messages import AIMessage, AIMessageChunk
from service.file_extraction_agent.core.model import ChatModelFallbackChain, ModelCallAttempt

from service.file_extraction_agent.manager import stream_completion_events
from service.file_extraction_agent.schemas import DocumentQaMessage


def _scripted_model():
    provider = Mock(spec=["bind_tools", "invoke"])
    provider.bind_tools.return_value = provider
    provider.invoke.side_effect = [
        AIMessage(content="我先看文档结构。", tool_calls=[
            {"id": "call-ls", "name": "ls", "args": {"path": ""}},
        ]),
        AIMessage(content="我搜索条款。", tool_calls=[
            {"id": "call-grep", "name": "grep", "args": {"query": "terminate", "max_results": 5}},
        ]),
        AIMessage(content="答案。", response_metadata={"finish_reason": "stop"}),
    ]
    return ChatModelFallbackChain([ModelCallAttempt("test_invoke", provider, False)]), provider


def _input(resource_path):
    return dict(completion_id="cmp_123", resource_path=resource_path,
                messages=[DocumentQaMessage(role="user", content="Can this contract be terminated early?")])


def test_stream_completion_events_yields_objects_and_terminal_completion(resource_path):
    model, provider = _scripted_model()
    events = list(stream_completion_events(**_input(resource_path), qa_model=model))
    assert [e["type"] for e in events] == [
        "completion.created", "source_indexed", "model_message", "tool_started", "tool_completed",
        "model_message", "tool_started", "tool_completed", "model_message", "completion.completed",
    ]
    history = provider.invoke.call_args.args[0]
    assert [m.tool_call_id for m in history if m.type == "tool"] == ["call-ls", "call-grep"]
    assert all("seq" not in event for event in events)


def test_tool_started_is_yielded_before_tool_execution(resource_path):
    model, provider = _scripted_model()
    stream = stream_completion_events(**_input(resource_path), qa_model=model)
    assert next(stream)["type"] == "completion.created"
    assert next(stream)["type"] == "source_indexed"
    assert next(stream)["type"] == "model_message"
    assert next(stream)["type"] == "tool_started"
    assert provider.invoke.call_count == 1
    assert next(stream)["type"] == "tool_completed"
    stream.close()


def test_cancel_before_execution_does_not_call_model(resource_path):
    model, provider = _scripted_model()
    events = list(stream_completion_events(**_input(resource_path), qa_model=model, should_stop=lambda: True))
    assert events[-1]["type"] == "completion.cancelled"
    provider.invoke.assert_not_called()


def test_cancel_after_model_drains_tools_without_next_model(resource_path):
    model, provider = _scripted_model()
    cancel = False
    stream = stream_completion_events(**_input(resource_path), qa_model=model, should_stop=lambda: cancel)
    assert next(stream)["type"] == "completion.created"
    assert next(stream)["type"] == "source_indexed"
    assert next(stream)["type"] == "model_message"
    cancel = True
    events = list(stream)
    assert [e["type"] for e in events] == ["tool_started", "tool_completed", "completion.cancelled"]
    assert events[1]["tool_call_id"] == "call-ls"
    assert provider.invoke.call_count == 1


@pytest.mark.parametrize("cancelled", [False, True])
def test_executor_failure_returns_entire_failed_batch(resource_path, monkeypatch, cancelled):
    from service.file_extraction_agent.core import loop
    stopped = False
    model, provider = _scripted_model()
    provider.invoke.side_effect = [AIMessage(content="读取", tool_calls=[
        {"id": "a", "name": "read", "args": {"path": "first"}},
        {"id": "b", "name": "read", "args": {"path": "second"}},
    ]), AIMessage(content="失败说明", response_metadata={"finish_reason": "stop"})]
    def fail(*args, **kwargs):
        nonlocal stopped
        stopped = cancelled
        raise RuntimeError("执行中断")
    monkeypatch.setattr(loop, "_execute_tools_parallel", fail)
    events = list(stream_completion_events(**_input(resource_path), qa_model=model, should_stop=lambda: stopped))
    replies = [e for e in events if e["type"] == "tool_failed"]
    assert [(e["tool_call_id"], e["args"]) for e in replies] == [("a", {"path": "first"}), ("b", {"path": "second"})]
    assert events[-1]["type"] == ("completion.cancelled" if cancelled else "completion.completed")
    assert provider.invoke.call_count == (1 if cancelled else 2)


def test_closing_event_stream_closes_message_generator(resource_path, monkeypatch):
    closed = []

    def messages(**kwargs):
        try:
            yield AIMessage(content="答案", response_metadata={"finish_reason": "stop"})
            raise AssertionError("不应请求下一条消息")
        finally:
            closed.append(True)

    monkeypatch.setattr(manager_module, "run_qa_stream", messages)
    stream = stream_completion_events(**_input(resource_path), qa_model=object())
    next(stream)
    next(stream)
    assert next(stream)["type"] == "model_message"
    stream.close()
    assert closed == [True]
