"""请求内事件转换与 protobuf 编码验证；模型配置加载独立在 test_model_config.py。"""

from __future__ import annotations

import json

from agent_proto import agent_pb2 as pb
from langchain_core.messages import AIMessage, ToolMessage
from routes.file_extraction_agent import encode_completion_event
from service.file_extraction_agent import application as runtime_module
from service.file_extraction_agent.schemas import DocumentQaMessage
from tests.async_helpers import async_items, wire_stream


async def test_runtime_yields_event_objects_with_sequence(resource_path, monkeypatch):
    """路由直接输出带编号的 protobuf 事件。"""
    monkeypatch.setattr(
        runtime_module,
        "run_qa_stream",
        lambda **kwargs: async_items(
            [AIMessage(content="你好\n世界", response_metadata={"finish_reason": "stop"})]
        ),
    )
    runtime = wire_stream(resource_path, object(), [DocumentQaMessage(role="user", content="问题")])
    assert [item async for item in runtime] == [
        pb.CompletionEvent(type="completion.created", status="in_progress", seq=1),
        pb.CompletionEvent(type="source_indexed", tool="source_index", result_json='{"ok":true}', seq=2),
        pb.CompletionEvent(
            type="model_message.done",
            message_id="",
            content="你好\n世界",
            tool_call_count=0,
            is_final=True,
            stop_signal="stop",
            seq=3,
        ),
        pb.CompletionEvent(type="completion.completed", status="completed", seq=4),
    ]


async def test_route_streams_without_manager(resource_path, monkeypatch):
    monkeypatch.setattr(
        runtime_module,
        "run_qa_stream",
        lambda **kwargs: async_items([AIMessage(content="回答", response_metadata={"finish_reason": "stop"})]),
    )
    events = [item async for item in wire_stream(resource_path, object(), [DocumentQaMessage(role="user", content="问题")])]
    assert [event.type for event in events] == [
        "completion.created",
        "source_indexed",
        "model_message.done",
        "completion.completed",
    ]
    assert [event.seq for event in events] == [1, 2, 3, 4]
    assert "completion_id" not in pb.CompletionEvent.DESCRIPTOR.fields_by_name


async def test_startup_events_only_acknowledge_without_reading_documents(resource_path, monkeypatch):
    from service.file_extraction_agent.core.tools.workspace import DocumentFileTree

    def forbidden(*args, **kwargs):
        raise AssertionError("启动通知不应遍历或读取文档")

    monkeypatch.setattr(DocumentFileTree, "entries", forbidden)
    monkeypatch.setattr(DocumentFileTree, "read", forbidden)
    stream = wire_stream(
        workspace=resource_path,
        messages=[DocumentQaMessage(role="user", content="问题")],
        qa_model=object(),
    )
    try:
        assert (await anext(stream)).type == "completion.created"
        source = await anext(stream)
        assert source.type == "source_indexed" and source.tool == "source_index"
        assert json.loads(source.result_json) == {"ok": True}
    finally:
        await stream.aclose()


async def test_stream_wraps_messages_and_pairs_same_name_calls(tmp_path, monkeypatch, resource_path):
    model_messages = [
        AIMessage(
            content="读取",
            tool_calls=[
                {"id": "a", "name": "read", "args": {"path": "first"}},
                {"id": "b", "name": "read", "args": {"path": "second"}},
            ],
        ),
        [
            ToolMessage(
                content="第一段",
                artifact={"ok": True, "text": "第一段"},
                tool_call_id="a",
                name="read",
                additional_kwargs={"tool_args": {"path": "first"}},
            ),
            ToolMessage(
                content="失败",
                artifact={"ok": False, "errors": [{"message": "bad path"}]},
                status="error",
                tool_call_id="b",
                name="read",
                additional_kwargs={"tool_args": {"path": "second"}},
            ),
        ],
        AIMessage(content="答案", response_metadata={"finish_reason": "stop"}),
    ]
    monkeypatch.setattr(
        runtime_module,
        "run_qa_stream",
        lambda *args, **kwargs: async_items([m for item in model_messages for m in (item if isinstance(item, list) else [item])]),
    )
    events = [
        item
        async for item in wire_stream(
            workspace=resource_path,
            messages=[DocumentQaMessage(role="user", content="问题")],
            qa_model=object(),
        )
    ]
    assert [e.type for e in events] == [
        "completion.created",
        "source_indexed",
        "model_message.done",
        "tool_started",
        "tool_started",
        "tool_completed",
        "tool_failed",
        "model_message.done",
        "completion.completed",
    ]
    results = [e for e in events if e.type in {"tool_completed", "tool_failed"}]
    assert [(e.tool_call_id, json.loads(e.args_json)["path"]) for e in results] == [("a", "first"), ("b", "second")]
    assert events[-2].is_final is True


async def test_route_outputs_protobuf_without_dictionary_boundary(tmp_path, monkeypatch, resource_path):
    monkeypatch.setattr(
        runtime_module,
        "run_qa_stream",
        lambda *args, **kwargs: async_items([AIMessage(content="完成", response_metadata={"finish_reason": "stop"})]),
    )
    events = [
        item
        async for item in wire_stream(
            workspace=resource_path,
            messages=[DocumentQaMessage(role="user", content="问题")],
            qa_model=object(),
        )
    ]
    assert all(isinstance(event, pb.CompletionEvent) for event in events)
    assert [event.type for event in events] == [
        "completion.created",
        "source_indexed",
        "model_message.done",
        "completion.completed",
    ]


def test_qa_records_text_from_responses_api_content_blocks(tmp_path):
    message = AIMessage(
        content=[
            {"type": "reasoning", "summary": []},
            {"type": "text", "text": "I will inspect root. "},
            {"type": "function_call", "name": "ls", "arguments": '{"path":""}'},
        ],
        tool_calls=[{"id": "call-1", "name": "ls", "args": {"path": ""}}],
    )
    event = encode_completion_event(runtime_module._model_message_event(message))
    assert event.content == "I will inspect root. "


def test_qa_records_terminal_stop_message_as_final_answer(tmp_path):
    message = AIMessage(content="最终答案。", response_metadata={"finish_reason": "stop"})
    event = encode_completion_event(runtime_module._model_message_event(message))
    assert event.content == "最终答案。"
    assert event.is_final is True
    assert event.stop_signal == "stop"


def test_qa_records_model_message_content_and_tool_calls_without_reasoning(tmp_path):
    message = AIMessage(
        content="I will inspect the root listing while calling a tool.",
        additional_kwargs={"reasoning_content": "hidden reasoning must not be persisted"},
        tool_calls=[{"id": "call-1", "name": "ls", "args": {"path": ""}}],
    )
    event = encode_completion_event(runtime_module._model_message_event(message))
    assert event == pb.CompletionEvent(
        message_id="",
        type="model_message.done",
        content="I will inspect the root listing while calling a tool.",
        tool_call_count=1,
        tool_calls=[pb.ToolCall(id="call-1", name="ls", args_json='{"path":""}')],
        is_final=False,
    )
    assert not event.HasField("stop_signal")
