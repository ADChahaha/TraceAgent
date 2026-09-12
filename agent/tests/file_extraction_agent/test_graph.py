from __future__ import annotations
import json

import asyncio
from unittest.mock import Mock, AsyncMock
import pytest
from langchain_core.messages import ToolMessage
from routes import file_extraction_agent as runtime_module
from langchain_core.messages import AIMessage
from service.file_extraction_agent.core.model import ConfiguredChatModel
from routes.file_extraction_agent import stream_completion
from service.file_extraction_agent.schemas import DocumentQaMessage


@pytest.fixture(autouse=True)
def fake_build_tools(monkeypatch):
    class _Tool:
        def __init__(self, name):
            self.name = name

        async def ainvoke(self, args):
            return {"ok": True, "text": "结果"}

    monkeypatch.setattr(
        "service.file_extraction_agent.core.loop.build_tools",
        lambda workspace: [_Tool(name) for name in ("ls", "grep", "read", "search_embedding")],
    )


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
    return (ConfiguredChatModel(provider, use_stream=False), provider)


def _input(resource_path):
    return dict(
        workspace=resource_path,
        messages=[DocumentQaMessage(role="user", content="Can this contract be terminated early?")],
    )


async def test_stream_completion_yields_protobuf_and_terminal_completion(resource_path):
    model, provider = _scripted_model()
    events = [item async for item in stream_completion(**_input(resource_path), qa_model=model)]
    assert [e.type for e in events] == [
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
    assert [event.seq for event in events] == list(range(1, len(events) + 1))


async def test_tool_started_is_yielded_before_tool_execution(resource_path):
    model, provider = _scripted_model()
    stream = stream_completion(**_input(resource_path), qa_model=model)
    assert (await anext(stream)).type == "completion.created"
    assert (await anext(stream)).type == "source_indexed"
    assert (await anext(stream)).type == "model_message.started"
    assert (await anext(stream)).type == "model_message.delta"
    assert (await anext(stream)).type == "model_message.done"
    assert (await anext(stream)).type == "tool_started"
    assert provider.ainvoke.call_count == 1
    assert (await anext(stream)).type == "tool_completed"
    await stream.aclose()


async def test_cancel_before_execution_does_not_call_model(resource_path):
    model, provider = _scripted_model()
    stream = stream_completion(**_input(resource_path), qa_model=model)
    async def consume():
        return [event async for event in stream]
    task = asyncio.create_task(consume())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await stream.aclose()
    provider.ainvoke.assert_not_called()


async def test_cancel_after_model_skips_tools_and_next_model(resource_path):
    model, provider = _scripted_model()
    stream = stream_completion(**_input(resource_path), qa_model=model)
    try:
        while (await anext(stream)).type != "model_message.done":
            pass
    finally:
        await stream.aclose()
    assert provider.ainvoke.call_count == 1


@pytest.mark.parametrize("cancelled", [False, True])
async def test_executor_failure_returns_entire_failed_batch(resource_path, monkeypatch, cancelled):
    from service.file_extraction_agent.core import executor

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

    entered = asyncio.Event()
    async def fail(*args, **kwargs):
        if cancelled:
            entered.set()
            await asyncio.Event().wait()
        raise RuntimeError("执行中断")

    monkeypatch.setattr(executor, "_execute_tools_parallel", fail)
    events = []
    async def consume():
        async for item in stream_completion(**_input(resource_path), qa_model=model):
            events.append(item)
    if cancelled:
        task = asyncio.create_task(consume())
        try:
            await asyncio.wait_for(entered.wait(), 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 2)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    else:
        await consume()
    replies = [e for e in events if e.type == "tool_failed"]
    assert [(e.tool_call_id, json.loads(e.args_json)) for e in replies] == ([] if cancelled else [
        ("a", {"path": "first"}),
        ("b", {"path": "second"}),
    ])
    assert [e.type for e in events if e.type.startswith("completion.")] == (
        ["completion.created"] if cancelled else ["completion.created", "completion.completed"]
    )
    assert provider.ainvoke.call_count == (1 if cancelled else 2)


@pytest.mark.parametrize("published_status", ["success", "error"])
async def test_executor_failure_preserves_published_results(resource_path, monkeypatch, published_status):
    from service.file_extraction_agent.core import executor

    model, provider = _scripted_model()
    calls = [
        {"id": "a", "name": "read", "args": {"path": "first"}},
        {"id": "b", "name": "read", "args": {"path": "second"}},
    ]
    provider.ainvoke.side_effect = [
        AIMessage(content="读取", tool_calls=calls),
        AIMessage(content="结果说明", response_metadata={"finish_reason": "stop"}),
    ]
    # 第二项先完成，验证发布顺序不影响模型历史中的调用顺序。
    result = {"ok": published_status == "success", "text": "原始结果"}
    published = ToolMessage(
        content="原始结果", tool_call_id="b", name="read", status=published_status,
        artifact=result, additional_kwargs={"tool_args": calls[1]["args"]},
    )

    async def fail_after_result(*args, on_result, **kwargs):
        on_result(published)
        raise RuntimeError("后续结果转换失败")

    monkeypatch.setattr(executor, "_execute_tools_parallel", fail_after_result)
    events = [event async for event in stream_completion(**_input(resource_path), qa_model=model)]
    replies = [event for event in events if event.type in {"tool_completed", "tool_failed"}]
    assert [event.tool_call_id for event in replies] == ["b", "a"]
    assert json.loads(replies[0].result_json) == result
    assert replies[0].type == ("tool_completed" if published_status == "success" else "tool_failed")
    assert replies[1].type == "tool_failed"
    history = [message for message in provider.ainvoke.call_args.args[0] if isinstance(message, ToolMessage)]
    assert [message.tool_call_id for message in history] == ["a", "b"]
    assert history[1] == published
    assert history[0].status == "error"
    assert history[0].artifact == json.loads(replies[1].result_json)


async def test_closing_event_stream_closes_message_generator(resource_path, monkeypatch):
    closed = []

    async def messages(**kwargs):
        try:
            yield AIMessage(content="答案", response_metadata={"finish_reason": "stop"})
            raise AssertionError("不应请求下一条消息")
        finally:
            closed.append(True)

    monkeypatch.setattr(runtime_module, "run_qa_stream", messages)
    stream = stream_completion(**_input(resource_path), qa_model=object())
    assert (await anext(stream)).type == "completion.created"
    assert (await anext(stream)).type == "source_indexed"
    assert (await anext(stream)).type == "model_message.done"
    await stream.aclose()
    assert closed == [True]


@pytest.mark.parametrize("phase", ["model", "tools"])
async def test_graph_task_cancellation_cleans_active_node(phase):
    from langchain_core.messages import HumanMessage
    from service.file_extraction_agent.core.graph import build_qa_graph
    started, cleaned = asyncio.Event(), asyncio.Event()
    calls = []
    model, _ = _scripted_model()
    async def wait():
        try:
            started.set()
            await asyncio.Event().wait()
        finally:
            cleaned.set()
    async def invoke(model, messages):
        calls.append("model")
        if phase == "model":
            await wait()
        return AIMessage(content="读取", tool_calls=[{"id": "a", "name": "read", "args": {}}])
    async def execute(*args, **kwargs):
        calls.append("tools")
        await wait()
        return []
    graph = build_qa_graph(model, [], invoke_model=invoke, execute_tools=execute)
    task = asyncio.create_task(graph.ainvoke({"messages": [HumanMessage(content="问题")]}))
    try:
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        assert cleaned.is_set()
        assert calls == (["model"] if phase == "model" else ["model", "tools"])
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


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
