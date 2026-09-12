"""core 类型化输出 → 路由直接生成 protobuf → 校验事件、编号、JSON 与关闭语义。"""

from contextlib import aclosing
from tests.async_helpers import wire_stream

import json

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from agent_proto import agent_pb2 as pb
from service.file_extraction_agent import application as route
from service.file_extraction_agent.core.contracts import (
    MessageDelta, MessageStarted, ModelFailed, ModelRetry,
)
from tests.async_helpers import async_items


async def test_stream_returns_protobuf_from_first_event():
    async with aclosing(wire_stream({}, object(), [])) as events:
        first = await anext(events)
        assert isinstance(first, pb.CompletionEvent)
        assert first == pb.CompletionEvent(type="completion.created", status="in_progress", seq=1)


async def test_typed_outputs_preserve_wire_events_and_json(monkeypatch):
    payload = {"number": 2 ** 60 + 1, "text": '中文\n"引号"', "null": None}
    outputs = [
        MessageStarted("attempt-1"),
        MessageDelta("attempt-1", "半句"),
        ModelRetry("attempt-1", 2, 5, 500, "暂时失败"),
        MessageStarted("attempt-2"),
        MessageDelta("attempt-2", "读取"),
        AIMessage(id="attempt-2", content="读取", tool_calls=[
            {"id": "call-1", "name": "read", "args": payload},
        ], response_metadata={"finish_reason": "tool_calls"}),
        ToolMessage(content="结果", artifact=payload, tool_call_id="call-1", name="read",
                    additional_kwargs={"tool_args": payload}),
        AIMessage(id="final", content="回答", response_metadata={"finish_reason": "stop"}),
    ]
    monkeypatch.setattr(route, "run_qa_stream", lambda **kwargs: async_items(outputs))
    events = [event async for event in wire_stream({}, object(), [])]
    assert all(isinstance(event, pb.CompletionEvent) for event in events)
    assert [event.seq for event in events] == list(range(1, len(events) + 1))
    assert [event.type for event in events] == [
        "completion.created", "source_indexed", "model_message.started", "model_message.delta",
        "model_request.retrying", "model_message.started", "model_message.delta",
        "model_message.done", "tool_started", "tool_completed", "model_message.done",
        "completion.completed",
    ]
    retry = events[4]
    assert (retry.message_id, retry.attempt, retry.max_attempts, retry.retry_delay_ms, retry.error) == (
        "attempt-1", 2, 5, 500, "暂时失败",
    )
    done, started, completed = events[7:10]
    assert done.HasField("is_final") and not done.is_final
    assert done.stop_signal == "tool_calls" and done.tool_call_count == 1
    assert json.loads(done.tool_calls[0].args_json) == payload
    assert json.loads(started.args_json) == payload
    assert json.loads(completed.args_json) == json.loads(completed.result_json) == payload
    assert events[-2].is_final and events[-2].content == "回答"
    assert events[-1].status == "completed"


@pytest.mark.parametrize("content, artifact, status, expected_type, expected_result", [
    ('{"ok": false, "value": null}', None, "success", "tool_failed", {"ok": False, "value": None}),
    ("纯文本", None, "success", "tool_completed", "纯文本"),
    ("结果", {"ok": True}, "error", "tool_failed", {"ok": True}),
])
async def test_tool_result_fallback_and_failure_status(
    monkeypatch, content, artifact, status, expected_type, expected_result,
):
    output = ToolMessage(content=content, artifact=artifact, status=status,
                         tool_call_id="call", name="read", additional_kwargs={"tool_args": {}})
    monkeypatch.setattr(route, "run_qa_stream", lambda **kwargs: async_items([output]))
    events = [event async for event in wire_stream({}, object(), [])]
    assert events[2].type == expected_type
    assert json.loads(events[2].result_json) == expected_result


@pytest.mark.parametrize("failure", [ModelFailed("attempt", "模型失败"), RuntimeError("执行失败")])
async def test_failure_closes_core_and_emits_one_terminal(monkeypatch, failure):
    closed = []

    async def outputs(**kwargs):
        try:
            yield MessageDelta("attempt", "正文")
            if isinstance(failure, Exception):
                raise failure
            yield failure
            raise AssertionError("失败后不应继续消费")
        finally:
            closed.append(True)

    monkeypatch.setattr(route, "run_qa_stream", outputs)
    events = [event async for event in wire_stream({}, object(), [])]
    assert events[-1].type == "completion.failed"
    assert events[-1].error_message == (str(failure) if isinstance(failure, Exception) else failure.error)
    assert [e.type for e in events if e.type.startswith("completion.")] == [
        "completion.created", "completion.failed",
    ]
    assert closed == [True]


async def test_encoding_failure_closes_core_and_keeps_sequence(monkeypatch):
    closed = []

    async def outputs(**kwargs):
        try:
            yield ToolMessage(content="非法数值", artifact={"value": float("nan")},
                              tool_call_id="a", name="read", additional_kwargs={"tool_args": {}})
        finally:
            closed.append(True)

    monkeypatch.setattr(route, "run_qa_stream", outputs)
    events = [event async for event in wire_stream({}, object(), [])]
    assert [e.type for e in events] == ["completion.created", "source_indexed", "completion.failed"]
    assert [e.seq for e in events] == [1, 2, 3]
    assert closed == [True]
