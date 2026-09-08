from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock
from tests.async_helpers import async_items, wait_event
from unittest.mock import Mock, AsyncMock
import pytest
from langchain_core.messages import ToolMessage
from service.file_extraction_agent import completion_runtime as runtime_module
from langchain_core.messages import AIMessage, AIMessageChunk
from service.file_extraction_agent.core.model import ConfiguredChatModel, ModelCallAttempt
from service.file_extraction_agent.completion_runtime import stream_completion_events
from service.file_extraction_agent.schemas import DocumentQaMessage


def _scripted_model():
    provider = Mock(spec=["bind_tools", "ainvoke"])
    provider.bind_tools.return_value = provider
    provider.ainvoke = AsyncMock()
    provider.ainvoke.side_effect = [
        AIMessage(
            content="我先看文档结构。", tool_calls=[{"id": "call-ls", "name": "ls", "args": {"path": ""}}]
        ),
        AIMessage(
            content="我搜索条款。",
            tool_calls=[
                {"id": "call-grep", "name": "grep", "args": {"query": "terminate", "max_results": 5}}
            ],
        ),
        AIMessage(content="答案。", response_metadata={"finish_reason": "stop"}),
    ]
    return (ConfiguredChatModel([ModelCallAttempt("test_invoke", provider, False)]), provider)


def _input(resource_path):
    return dict(
        resource_path=resource_path,
        messages=[DocumentQaMessage(role="user", content="Can this contract be terminated early?")],
    )


async def test_stream_completion_events_yields_objects_and_terminal_completion(resource_path):
    model, provider = _scripted_model()
    events = [item async for item in stream_completion_events(**_input(resource_path), qa_model=model)]
    assert [e["type"] for e in events] == [
        "completion.created",
        "source_indexed",
        "model_message.started",
        "model_message.delta",
        "model_message.done",
        "tool_started",
        "tool_completed",
        "model_message.started",
        "model_message.delta",
        "model_message.done",
        "tool_started",
        "tool_completed",
        "model_message.started",
        "model_message.delta",
        "model_message.done",
        "completion.completed",
    ]
    history = provider.ainvoke.call_args.args[0]
    assert [m.tool_call_id for m in history if m.type == "tool"] == ["call-ls", "call-grep"]
    assert all(("seq" not in event for event in events))


async def test_tool_started_is_yielded_before_tool_execution(resource_path):
    model, provider = _scripted_model()
    stream = stream_completion_events(**_input(resource_path), qa_model=model)
    assert (await anext(stream))["type"] == "completion.created"
    assert (await anext(stream))["type"] == "source_indexed"
    assert (await anext(stream))["type"] == "model_message.started"
    assert (await anext(stream))["type"] == "model_message.delta"
    assert (await anext(stream))["type"] == "model_message.done"
    assert (await anext(stream))["type"] == "tool_started"
    assert provider.ainvoke.call_count == 1
    assert (await anext(stream))["type"] == "tool_completed"
    await stream.aclose()


async def test_cancel_before_execution_does_not_call_model(resource_path):
    model, provider = _scripted_model()
    events = [
        item
        async for item in stream_completion_events(
            **_input(resource_path), qa_model=model, should_stop=lambda: True
        )
    ]
    assert events[-1]["type"] == "completion.cancelled"
    provider.ainvoke.assert_not_called()


async def test_cancel_after_model_drains_tools_without_next_model(resource_path):
    model, provider = _scripted_model()
    cancel = False
    stream = stream_completion_events(**_input(resource_path), qa_model=model, should_stop=lambda: cancel)
    assert (await anext(stream))["type"] == "completion.created"
    assert (await anext(stream))["type"] == "source_indexed"
    assert (await anext(stream))["type"] == "model_message.started"
    assert (await anext(stream))["type"] == "model_message.delta"
    assert (await anext(stream))["type"] == "model_message.done"
    cancel = True
    events = [item async for item in stream]
    assert [e["type"] for e in events] == ["tool_started", "tool_completed", "completion.cancelled"]
    assert events[1]["tool_call_id"] == "call-ls"
    assert provider.ainvoke.call_count == 1


@pytest.mark.parametrize("cancelled", [False, True])
async def test_executor_failure_returns_entire_failed_batch(resource_path, monkeypatch, cancelled):
    from service.file_extraction_agent.core import executor

    stopped = False
    model, provider = _scripted_model()
    provider.ainvoke.side_effect = [
        AIMessage(
            content="读取",
            tool_calls=[
                {"id": "a", "name": "read", "args": {"path": "first"}},
                {"id": "b", "name": "read", "args": {"path": "second"}},
            ],
        ),
        AIMessage(content="失败说明", response_metadata={"finish_reason": "stop"}),
    ]

    def fail(*args, **kwargs):
        nonlocal stopped
        stopped = cancelled
        raise RuntimeError("执行中断")

    monkeypatch.setattr(executor, "_execute_tools_parallel", fail)
    events = [
        item
        async for item in stream_completion_events(
            **_input(resource_path), qa_model=model, should_stop=lambda: stopped
        )
    ]
    replies = [e for e in events if e["type"] == "tool_failed"]
    assert [(e["tool_call_id"], e["args"]) for e in replies] == [
        ("a", {"path": "first"}),
        ("b", {"path": "second"}),
    ]
    assert events[-1]["type"] == ("completion.cancelled" if cancelled else "completion.completed")
    assert provider.ainvoke.call_count == (1 if cancelled else 2)


async def test_closing_event_stream_closes_message_generator(resource_path, monkeypatch):
    closed = []

    async def messages(**kwargs):
        try:
            yield AIMessage(content="答案", response_metadata={"finish_reason": "stop"})
            raise AssertionError("不应请求下一条消息")
        finally:
            closed.append(True)

    monkeypatch.setattr(runtime_module, "run_qa_stream", messages)
    stream = stream_completion_events(**_input(resource_path), qa_model=object())
    await anext(stream)
    await anext(stream)
    assert (await anext(stream))["type"] == "model_message.done"
    await stream.aclose()
    assert closed == [True]


@pytest.mark.parametrize("cancel_at", ["before_model", "during_model", "after_model", "after_tools"])
async def test_graph_owns_cancellation_and_drains_published_batch(cancel_at):
    from langchain_core.messages import HumanMessage
    from service.file_extraction_agent.core.graph import build_qa_graph

    stopped = cancel_at == "before_model"
    model, _ = _scripted_model()
    calls = [
        {"id": "a", "name": "read", "args": {"path": "first"}},
        {"id": "b", "name": "read", "args": {"path": "second"}},
    ]

    async def invoke_model(model, messages):
        nonlocal stopped
        if cancel_at == "during_model":
            stopped = True
        return AIMessage(content="读取", tool_calls=calls)

    invoke = AsyncMock(side_effect=invoke_model)
    execute = AsyncMock(return_value=[
        ToolMessage(content="正文", tool_call_id=call["id"]) for call in calls
    ])
    graph = build_qa_graph(model, [], invoke_model=invoke, execute_tools=execute,
                           should_stop=lambda: stopped)
    updates = graph.astream({"messages": [HumanMessage(content="问题")]}, stream_mode="updates")
    published = []
    async for update in updates:
        for node, batch in update.items():
            if batch["messages"]:
                published.append((node, batch["messages"]))
                if (node == "agent" and cancel_at == "after_model") or (
                    node == "tools" and cancel_at == "after_tools"
                ):
                    stopped = True
    if cancel_at in {"before_model", "during_model"}:
        assert published == []
        execute.assert_not_called()
        assert invoke.call_count == (cancel_at == "during_model")
    else:
        assert [node for node, _ in published] == ["agent", "tools"]
        assert [message.tool_call_id for message in published[1][1]] == ["a", "b"]
        assert invoke.call_count == execute.call_count == 1


@pytest.mark.parametrize("ids", [["", "b"], ["a", "a"]])
async def test_graph_rejects_invalid_tool_ids_before_execution(ids):
    from langchain_core.messages import HumanMessage
    from service.file_extraction_agent.core.graph import build_qa_graph

    model, _ = _scripted_model()
    invoke = AsyncMock(side_effect=[
        AIMessage(content="读取", tool_calls=[{"id": id_, "name": "read", "args": {}} for id_ in ids]),
        AIMessage(content="结束", response_metadata={"finish_reason": "stop"}),
    ])
    execute = AsyncMock(return_value=[])
    graph = build_qa_graph(model, [], invoke_model=invoke, execute_tools=execute)
    with pytest.raises(ValueError, match="unique non-empty IDs"):
        await graph.ainvoke({"messages": [HumanMessage(content="问题")]})
    execute.assert_not_called()
