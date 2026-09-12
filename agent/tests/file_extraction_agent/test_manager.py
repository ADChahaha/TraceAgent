"""请求内事件转换和模型配置验证；旧注册表生命周期由 RPC 测试替代。"""
from tests.async_helpers import wire_stream

from routes.file_extraction_agent import encode_completion_event
import pytest
import json
from agent_proto import agent_pb2 as pb
from langchain_core.messages import AIMessage, ToolMessage
from tests.async_helpers import async_items
from service.file_extraction_agent.core import model as model_module
from service.file_extraction_agent.core.model import build_chat_model, normalize_model_config
from service.file_extraction_agent import application as runtime_module
from tests.async_helpers import wire_stream as stream_completion
from service.file_extraction_agent.schemas import DocumentQaMessage, ModelConfig, RunOptions

async def test_runtime_yields_event_objects_with_sequence(resource_path, monkeypatch):
    """路由直接输出带编号的 protobuf 事件。"""
    monkeypatch.setattr(
        runtime_module,
        "run_qa_stream",
        lambda **kwargs: async_items(
            [
                AIMessage(content="你好\n世界", response_metadata={"finish_reason": "stop"}),
            ]
        ),
    )
    runtime = stream_completion(resource_path, object(), [DocumentQaMessage(role="user", content="问题")])
    assert [item async for item in runtime] == [
        pb.CompletionEvent(type="completion.created", status="in_progress", seq=1),
        pb.CompletionEvent(type="source_indexed", tool="source_index", result_json='{"ok":true}', seq=2),
        pb.CompletionEvent(type="model_message.done", message_id="", content="你好\n世界",
                           tool_call_count=0, is_final=True, stop_signal="stop", seq=3),
        pb.CompletionEvent(type="completion.completed", status="completed", seq=4),
    ]


async def test_route_streams_without_manager(resource_path, monkeypatch):
    from service.file_extraction_agent import application as route

    monkeypatch.setattr(
        route,
        "run_qa_stream",
        lambda **kwargs: async_items(
            [AIMessage(content="回答", response_metadata={"finish_reason": "stop"})]
        ),
    )
    runtime = wire_stream(
        resource_path, object(), [DocumentQaMessage(role="user", content="问题")]
    )
    events = [item async for item in runtime]
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
    from langchain_core.messages import AIMessage, ToolMessage

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
    monkeypatch.setattr(runtime_module, "run_qa_stream", lambda *args, **kwargs: async_items([m for item in model_messages for m in (item if isinstance(item, list) else [item])]))
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
        lambda *args, **kwargs: async_items(
            [AIMessage(content="完成", response_metadata={"finish_reason": "stop"})]
        ),
    )
    events = [
        item
        async for item in wire_stream(
            workspace=resource_path,
            messages=[DocumentQaMessage(role="user", content="问题")],
            qa_model=object(),
        )
    ]
    assert all((isinstance(event, pb.CompletionEvent) for event in events))
    assert [event.type for event in events] == [
        "completion.created", "source_indexed", "model_message.done", "completion.completed",
    ]


def test_normalize_model_config_loads_default_env_file(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                'BASE_URL="https://example.com/v1"',
                'OPENAI_API_KEY="key"',
                'MODEL="qa"',
                'MODEL_API_TRANSPORT="chat_completions"',
                'TEMPERATURE="0.1"',
                'TOP_P="0.9"',
                'TOP_K="40"',
                'REASONING_EFFORT="high"',
                'MODEL_MAX_RETRIES="8"',
                'MODEL_REQUEST_TIMEOUT="120"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(model_module, "_candidate_env_paths", lambda: [env_path])
    missing_cwd = tmp_path / "missing"
    missing_cwd.mkdir()
    monkeypatch.chdir(missing_cwd)
    for name in (
        "BASE_URL",
        "API_KEY",
        "OPENAI_API_KEY",
        "MODEL",
        "MODEL_API_TRANSPORT",
        "TEMPERATURE",
        "TOP_P",
        "TOP_K",
        "REASONING_EFFORT",
        "MODEL_MAX_RETRIES",
        "MODEL_REQUEST_TIMEOUT",
    ):
        monkeypatch.delenv(name, raising=False)
    config = normalize_model_config(None)
    assert config.base_url == "https://example.com/v1"
    assert config.api_key == "key"
    assert config.model_name == "qa"
    assert config.api_transport == "chat_completions"
    assert config.temperature == 0.1
    assert config.top_p == 0.9
    assert config.top_k == 40
    assert config.reasoning_effort == "high"
    assert config.max_retries == 8
    assert config.request_timeout == 120.0


def test_build_chat_model_builds_responses_transport_by_default(monkeypatch):
    captured = []

    class FakeChatOpenAI:

        def __init__(self, **kwargs):
            captured.append(kwargs)

    monkeypatch.setattr(model_module, "_chat_model_class", lambda: FakeChatOpenAI)
    model = build_chat_model(
        ModelConfig(base_url="https://example.com/v1", api_key="key", model_name="qa"), "qa"
    )
    assert model.use_stream is True
    assert isinstance(model.model, FakeChatOpenAI)
    assert [kwargs["use_responses_api"] for kwargs in captured] == [True]
    assert [kwargs["streaming"] for kwargs in captured] == [True]
    assert [kwargs["timeout"] for kwargs in captured] == [8.0]


def test_build_chat_model_builds_chat_completions_transport_when_configured(monkeypatch):
    captured = []

    class FakeChatOpenAI:

        def __init__(self, **kwargs):
            captured.append(kwargs)

    monkeypatch.setattr(model_module, "_chat_model_class", lambda: FakeChatOpenAI)
    model = build_chat_model(
        ModelConfig(
            base_url="https://example.com/v1",
            api_key="key",
            model_name="qa",
            api_transport="chat_completions",
        ),
        "qa",
    )
    assert model.use_stream is True
    assert isinstance(model.model, FakeChatOpenAI)
    assert [kwargs["use_responses_api"] for kwargs in captured] == [False]
    assert [kwargs["streaming"] for kwargs in captured] == [True]


def test_build_chat_model_rejects_unknown_transport():
    with pytest.raises(ValueError, match="MODEL_API_TRANSPORT"):
        build_chat_model(ModelConfig(model_name="qa", api_transport="auto"), "qa")


def test_normalize_model_config_rejects_untyped_dict_input():
    with pytest.raises(TypeError, match="unexpected model config type"):
        normalize_model_config({"model": "qa"})


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
        message_id="", type="model_message.done",
        content="I will inspect the root listing while calling a tool.", tool_call_count=1,
        tool_calls=[pb.ToolCall(id="call-1", name="ls", args_json='{"path":""}')],
        is_final=False,
    )
    assert not event.HasField("stop_signal")
