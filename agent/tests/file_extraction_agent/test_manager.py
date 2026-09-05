from __future__ import annotations

from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from service.file_extraction_agent.core import model as model_module
from service.file_extraction_agent.core.model import build_chat_model, normalize_model_config
from service.file_extraction_agent import manager as manager_module
from service.file_extraction_agent.manager import (
    ActiveCompletion,
    CompletionManager,
)
from service.file_extraction_agent.schemas import DocumentQaMessage, ModelConfig, RunOptions


@pytest.mark.parametrize("ending", ["completed", "failed", "cancelled"])
def test_stream_numbers_messages_and_terminal_once(tmp_path, monkeypatch, ending, resource_path):
    import json
    manager = CompletionManager()

    def messages(*args, **kwargs):
        yield AIMessage(content="答案", response_metadata={"finish_reason": "stop"})
        if ending == "failed":
            raise RuntimeError("provider failed")
        if ending == "cancelled":
            manager.terminate("cmp_seq")

    monkeypatch.setattr(manager_module, "build_qa_model", lambda config: object())
    monkeypatch.setattr(manager_module, "run_qa_stream", messages)
    frames = list(manager.create(
        completion_id="cmp_seq", run_options=RunOptions(),
        resource_path=resource_path,
        messages=[DocumentQaMessage(role="user", content="问题")],
    ))
    events = [json.loads(frame.split("data: ", 1)[1]) for frame in frames]
    assert all("id" not in event and "completion_id" not in event for event in events)
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    assert events[-1]["type"] == f"completion.{ending}"
    if ending == "failed":
        assert [event["tool"] for event in events if event["type"] == "tool_failed"] == ["qa"]
    assert sum(manager_module._terminal_status(event) is not None for event in events) == 1


def test_startup_events_only_acknowledge_without_reading_documents(resource_path, monkeypatch):
    from service.file_extraction_agent.core.tools.workspace import DocumentFileTree

    def forbidden(*args, **kwargs):
        raise AssertionError("启动通知不应遍历或读取文档")

    monkeypatch.setattr(DocumentFileTree, "entries", forbidden)
    monkeypatch.setattr(DocumentFileTree, "read", forbidden)
    stream = manager_module.stream_completion_events(
        resource_path=resource_path,
        messages=[DocumentQaMessage(role="user", content="问题")], qa_model=object(),
    )
    try:
        created = next(stream)
        source = next(stream)
        assert created == {"type": "completion.created", "status": "in_progress"}
        assert source == {"type": "source_indexed", "tool": "source_index", "result": {"ok": True}}
    finally:
        stream.close()


def test_runtime_cancel_drains_real_graph_batch_and_skips_next_model(tmp_path, monkeypatch, resource_path):
    import json
    from unittest.mock import Mock
    from service.file_extraction_agent.core.model import ChatModelFallbackChain, ModelCallAttempt
    from service.file_extraction_agent.core import loop
    started, release = threading.Event(), threading.Event()
    provider = Mock(spec=["bind_tools", "invoke"])
    provider.bind_tools.return_value = provider
    provider.invoke.side_effect = [AIMessage(content="读取", tool_calls=[
        {"id": "read-1", "name": "read", "args": {"path": "first"}},
        {"id": "read-2", "name": "read", "args": {"path": "second"}},
    ])]

    class Reader:
        name = "read"

        def invoke(self, args):
            started.set()
            assert release.wait(2)
            return {"ok": True, "text": args["path"]}

    monkeypatch.setattr(loop, "build_tools", lambda state: [Reader()])
    monkeypatch.setattr(manager_module, "build_qa_model", lambda config:
        ChatModelFallbackChain([ModelCallAttempt("test", provider, False)]))
    manager = CompletionManager()
    stream = manager.create(
        completion_id="cmp_real_cancel", run_options=RunOptions(),
        resource_path=resource_path,
        messages=[DocumentQaMessage(role="user", content="问题")],
    )
    frames = []
    done = threading.Event()

    def consume():
        try:
            frames.extend(stream)
        finally:
            done.set()

    thread = threading.Thread(target=consume, daemon=True)
    thread.start()
    try:
        assert started.wait(1)
        assert manager.terminate("cmp_real_cancel")["status"] == "cancelling"
        assert not done.wait(0.05)
    finally:
        release.set()
        thread.join(2)
    assert done.is_set()
    events = [json.loads(frame.split("data: ", 1)[1]) for frame in frames]
    results = [event for event in events if event["type"] == "tool_completed"]
    assert [(e["tool_call_id"], e["result"]["text"]) for e in results] == [("read-1", "first"), ("read-2", "second")]
    assert events[-1]["type"] == "completion.cancelled"
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    assert provider.invoke.call_count == 1
    assert Path(resource_path).is_dir()


def test_manager_wraps_messages_and_pairs_same_name_calls(tmp_path, monkeypatch, resource_path):
    from langchain_core.messages import AIMessage, ToolMessage
    model_messages = [
        AIMessage(content="读取", tool_calls=[
            {"id": "a", "name": "read", "args": {"path": "first"}},
            {"id": "b", "name": "read", "args": {"path": "second"}},
        ]),
        [ToolMessage(content="第一段", artifact={"ok": True, "text": "第一段"}, tool_call_id="a", name="read", additional_kwargs={"tool_args": {"path": "first"}}),
        ToolMessage(content="失败", artifact={"ok": False, "errors": [{"message": "bad path"}]}, status="error", tool_call_id="b", name="read", additional_kwargs={"tool_args": {"path": "second"}})],
        AIMessage(content="答案", response_metadata={"finish_reason": "stop"}),
    ]
    monkeypatch.setattr(manager_module, "run_qa_stream", lambda *args, **kwargs: iter(model_messages))
    events = list(manager_module.stream_completion_events(resource_path=resource_path, messages=[DocumentQaMessage(role="user", content="问题")], qa_model=object()))
    assert [e["type"] for e in events] == [
        "completion.created", "source_indexed", "model_message", "tool_started", "tool_started",
        "tool_completed", "tool_failed", "model_message", "completion.completed",
    ]
    results = [e for e in events if e["type"] in {"tool_completed", "tool_failed"}]
    assert [(e["tool_call_id"], e["args"]["path"]) for e in results] == [("a", "first"), ("b", "second")]
    assert events[-2]["is_final"] is True


def test_graph_keeps_events_as_objects_until_stream_boundary(tmp_path, monkeypatch, resource_path):
    monkeypatch.setattr(manager_module, "run_qa_stream", lambda *args, **kwargs: iter([AIMessage(content="完成", response_metadata={"finish_reason": "stop"})]))
    events = list(manager_module.stream_completion_events(resource_path=resource_path, messages=[DocumentQaMessage(role="user", content="问题")], qa_model=object()))
    assert all(isinstance(event, dict) for event in events)
    assert [event["type"] for event in events] == [
        "completion.created", "source_indexed", "model_message", "completion.completed",
    ]


def test_stream_encodes_runtime_failure_with_special_characters(tmp_path, monkeypatch, resource_path):
    import json
    error = '失败：第一行\n第二行\t"引号"\\路径'

    def fail(*args, **kwargs):
        raise RuntimeError(error)

    monkeypatch.setattr(manager_module, "build_qa_model", lambda config: object())
    monkeypatch.setattr(manager_module, "stream_completion_events", fail)
    frames = _frames(CompletionManager().create(
        completion_id="cmp_error", run_options=RunOptions(),
        resource_path=resource_path,
        messages=[DocumentQaMessage(role="user", content="问题")],
    ))
    assert len(frames) == 1
    event_line, data_line, _, _ = frames[0].split("\n")
    assert event_line == "event: completion.failed"
    assert json.loads(data_line.removeprefix("data: "))["error_message"] == error








@pytest.mark.parametrize("marker", ["completed", "cancelled", "failed"])
def test_stream_preserves_terminal_words_in_data(tmp_path, monkeypatch, marker, resource_path):
    import json
    ordinary = {"type": "model_message", "content": f"event: completion.{marker}"}
    terminal = {"type": "completion.completed", "status": "completed"}
    monkeypatch.setattr(manager_module, "build_qa_model", lambda config: object())
    monkeypatch.setattr(manager_module, "stream_completion_events", lambda *a, **k: iter([ordinary, terminal]))
    frames = _frames(CompletionManager().create(
        completion_id="cmp_words", run_options=RunOptions(),
        resource_path=resource_path,
        messages=[DocumentQaMessage(role="user", content="问题")],
    ))
    assert [json.loads(frame.split("data: ", 1)[1]) for frame in frames] == [ordinary, terminal]


@pytest.mark.parametrize("status", ["completed", "cancelled", "failed"])
def test_terminal_status_reads_only_event_type(status):
    event = {"type": f"completion.{status}", "content": "event: completion.cancelled"}
    assert manager_module._terminal_status(event) == status


@pytest.mark.parametrize("event", [
    {"type": "completion.completed.extra"},
    {"type": "model_message", "status": "failed", "content": "event: completion.failed"},
    {"content": "event: completion.cancelled"},
])
def test_terminal_detection_requires_exact_event_type(event):
    assert manager_module._terminal_status(event) is None


def test_create_completion_stream_builds_completion_input_and_runs_graph(monkeypatch, resource_path):
    captured = {}

    def fake_build_qa_model(config):
        captured["config"] = config
        return "qa-model"

    def fake_stream_completion_events(*, qa_model, **kwargs):
        captured["has_completion_id"] = "completion_id" in kwargs
        captured["document_root"] = kwargs["resource_path"]
        captured["messages"] = kwargs["messages"]
        captured["model"] = qa_model
        yield {'type': 'completion.completed'}

    monkeypatch.setattr("service.file_extraction_agent.manager.build_qa_model", fake_build_qa_model)
    monkeypatch.setattr("service.file_extraction_agent.manager.stream_completion_events", fake_stream_completion_events)

    manager = CompletionManager()
    events = _frames(
        manager.create(
            completion_id="cmp_123",
            resource_path=resource_path,
            messages=[DocumentQaMessage(role="user", content="问题")],
            model_config=ModelConfig(model_name="qa"),
        )
    )

    assert events == ['event: completion.completed\ndata: {"type":"completion.completed"}\n\n']
    assert captured["has_completion_id"] is False
    assert captured["document_root"] == resource_path
    assert captured["messages"][0].content == "问题"
    assert captured["model"] == "qa-model"


def test_create_completion_stream_validates_input_before_iteration(monkeypatch, resource_path):
    called = False

    def fake_build_qa_model(config):
        nonlocal called
        called = True
        return "qa-model"

    monkeypatch.setattr("service.file_extraction_agent.manager.build_qa_model", fake_build_qa_model)

    manager = CompletionManager()
    with pytest.raises(ValueError, match="resource_path"):
        manager.create(
            completion_id="cmp_123",
            resource_path="",
            messages=[DocumentQaMessage(role="user", content="问题")],
            model_config=ModelConfig(model_name="qa"),
        )

    assert called is False


def test_create_completion_stream_registers_active_completion_before_iteration(monkeypatch, resource_path):
    graph_called = threading.Event()

    def fake_build_qa_model(config):
        return "qa-model"

    def fake_stream_completion_events(*, qa_model, **kwargs):
        del qa_model
        graph_called.set()
        yield {'type': 'completion.completed'}

    monkeypatch.setattr("service.file_extraction_agent.manager.build_qa_model", fake_build_qa_model)
    monkeypatch.setattr("service.file_extraction_agent.manager.stream_completion_events", fake_stream_completion_events)

    manager = CompletionManager()
    stream = manager.create(
        completion_id="cmp_early_cancel",
        resource_path=resource_path,
        messages=[DocumentQaMessage(role="user", content="问题")],
        model_config=ModelConfig(model_name="qa"),
    )

    assert manager.terminate("cmp_early_cancel") == {"id": "cmp_early_cancel", "status": "cancelling"}
    assert _frames(stream) == [
        'event: completion.cancelled\ndata: {"type":"completion.cancelled","status":"cancelled"}\n\n'
    ]
    assert not graph_called.is_set()
    assert manager.terminate("cmp_early_cancel") == {"id": "cmp_early_cancel", "status": "not_found"}


def test_create_completion_stream_cancel_does_not_wait_for_blocked_graph(monkeypatch, resource_path):
    graph_started = threading.Event()
    release_graph = threading.Event()

    def fake_build_qa_model(config):
        del config
        return "qa-model"

    def fake_stream_completion_events(*, qa_model, **kwargs):
        del qa_model
        graph_started.set()
        release_graph.wait(timeout=1.0)
        yield {'type': 'completion.completed'}

    monkeypatch.setattr("service.file_extraction_agent.manager.build_qa_model", fake_build_qa_model)
    monkeypatch.setattr("service.file_extraction_agent.manager.stream_completion_events", fake_stream_completion_events)

    manager = CompletionManager()
    stream = manager.create(
        completion_id="cmp_blocked",
        resource_path=resource_path,
        messages=[DocumentQaMessage(role="user", content="问题")],
        model_config=ModelConfig(model_name="qa"),
    )
    events: list[str] = []
    stream_done = threading.Event()

    def consume_stream():
        events.extend(_frames(stream))
        stream_done.set()

    consumer_thread = threading.Thread(target=consume_stream, daemon=True)
    consumer_thread.start()

    assert graph_started.wait(timeout=0.5)
    assert manager.terminate("cmp_blocked") == {"id": "cmp_blocked", "status": "cancelling"}
    started_at = time.monotonic()
    try:
        assert stream_done.wait(timeout=0.25)
    finally:
        release_graph.set()
        consumer_thread.join(timeout=1.0)

    assert time.monotonic() - started_at < 0.25
    assert events == [
        'event: completion.cancelled\ndata: {"type":"completion.cancelled","status":"cancelled"}\n\n'
    ]
    assert manager.terminate("cmp_blocked") == {"id": "cmp_blocked", "status": "not_found"}


def test_create_completion_stream_flushes_committed_events_before_cancel(monkeypatch, resource_path):
    second_event_reached_graph = threading.Event()
    release_graph = threading.Event()

    def fake_build_qa_model(config):
        del config
        return "qa-model"

    def fake_stream_completion_events(*, qa_model, **kwargs):
        del qa_model
        yield {'type': 'model_message', 'content': 'first'}
        second_event_reached_graph.set()
        yield {'type': 'tool_completed', 'tool': 'read'}
        release_graph.wait(timeout=1.0)
        yield {'type': 'completion.completed', 'status': 'completed'}

    monkeypatch.setattr("service.file_extraction_agent.manager.build_qa_model", fake_build_qa_model)
    monkeypatch.setattr("service.file_extraction_agent.manager.stream_completion_events", fake_stream_completion_events)

    manager = CompletionManager()
    stream = iter(
        manager.create(
            completion_id="cmp_flush",
            resource_path=resource_path,
            messages=[DocumentQaMessage(role="user", content="问题")],
            model_config=ModelConfig(model_name="qa"),
        )
    )

    first_event = _without_seq(next(stream))
    assert second_event_reached_graph.wait(timeout=0.5)
    time.sleep(0.02)
    assert manager.terminate("cmp_flush") == {"id": "cmp_flush", "status": "cancelling"}
    try:
        remaining_events = _frames(stream)
    finally:
        release_graph.set()

    assert first_event == 'event: model_message\ndata: {"type":"model_message","content":"first"}\n\n'
    assert remaining_events == [
        'event: tool_completed\ndata: {"type":"tool_completed","tool":"read"}\n\n',
        'event: completion.cancelled\ndata: {"type":"completion.cancelled","status":"cancelled"}\n\n',
    ]
    assert manager.terminate("cmp_flush") == {"id": "cmp_flush", "status": "not_found"}


def test_should_stop_is_wired_to_cancel_requested(monkeypatch, resource_path):
    batch_running = threading.Event()
    release_batch = threading.Event()
    seen_should_stop = {"value": None}

    def fake_build_qa_model(config):
        del config
        return "qa-model"

    def fake_stream_completion_events(*, qa_model, **kwargs):
        del qa_model
        seen_should_stop["value"] = kwargs.get("should_stop")
        batch_running.set()
        release_batch.wait(timeout=1.0)
        yield {'type': 'completion.completed', 'status': 'completed'}

    monkeypatch.setattr("service.file_extraction_agent.manager.build_qa_model", fake_build_qa_model)
    monkeypatch.setattr("service.file_extraction_agent.manager.stream_completion_events", fake_stream_completion_events)

    manager = CompletionManager()
    stream = manager.create(
        completion_id="cmp_ws",
        resource_path=resource_path,
        messages=[DocumentQaMessage(role="user", content="问题")],
        model_config=ModelConfig(model_name="qa"),
    )
    stream_done = threading.Event()

    def consume_stream():
        _frames(stream)
        stream_done.set()

    consumer_thread = threading.Thread(target=consume_stream, daemon=True)
    consumer_thread.start()

    assert batch_running.wait(timeout=0.5)
    assert callable(seen_should_stop["value"])
    assert seen_should_stop["value"]() is False
    assert manager.terminate("cmp_ws") == {"id": "cmp_ws", "status": "cancelling"}
    assert seen_should_stop["value"]() is True
    release_batch.set()
    consumer_thread.join(timeout=1.0)
    assert stream_done.is_set() is True
    assert manager.terminate("cmp_ws") == {"id": "cmp_ws", "status": "not_found"}


def test_terminate_defers_cancel_until_active_tool_batch_settles(monkeypatch, resource_path):
    batch_running = threading.Event()
    release_batch = threading.Event()

    def fake_build_qa_model(config):
        del config
        return "qa-model"

    def fake_stream_completion_events(*, qa_model, **kwargs):
        del qa_model
        yield {"type": "model_message", "content": "读取", "tool_calls": [{"id": "deferred-read", "name": "read", "args": {}}]}
        batch_running.set()
        release_batch.wait(timeout=1.0)
        yield {'type': 'tool_completed', 'tool': 'read', 'tool_call_id': 'deferred-read'}

        yield {'type': 'completion.cancelled', 'status': 'cancelled'}

    monkeypatch.setattr("service.file_extraction_agent.manager.build_qa_model", fake_build_qa_model)
    monkeypatch.setattr("service.file_extraction_agent.manager.stream_completion_events", fake_stream_completion_events)

    manager = CompletionManager()
    stream = manager.create(
        completion_id="cmp_deferred",
        resource_path=resource_path,
        messages=[DocumentQaMessage(role="user", content="问题")],
        model_config=ModelConfig(model_name="qa"),
    )
    events: list[str] = []
    stream_done = threading.Event()

    def consume_stream():
        events.extend(_frames(stream))
        stream_done.set()

    consumer_thread = threading.Thread(target=consume_stream, daemon=True)
    consumer_thread.start()

    assert batch_running.wait(timeout=0.5)
    assert manager.terminate("cmp_deferred") == {"id": "cmp_deferred", "status": "cancelling"}
    try:
        assert stream_done.wait(timeout=0.25) is False
    finally:
        release_batch.set()
        consumer_thread.join(timeout=1.0)

    tool_events = [event for event in events if "tool_completed" in event]
    assert tool_events == [
        'event: tool_completed\ndata: {"type":"tool_completed","tool":"read","tool_call_id":"deferred-read"}\n\n'
    ]
    assert events[-1] == (
        'event: completion.cancelled\ndata: {"type":"completion.cancelled","status":"cancelled"}\n\n'
    )
    assert manager.terminate("cmp_deferred") == {"id": "cmp_deferred", "status": "not_found"}


def test_create_completion_stream_emits_only_one_terminal_event_when_cancel_races_completed(monkeypatch, resource_path):
    graph_can_complete = threading.Event()

    def fake_build_qa_model(config):
        del config
        return "qa-model"

    def fake_stream_completion_events(*, qa_model, **kwargs):
        del qa_model
        graph_can_complete.wait(timeout=1.0)
        yield {'type': 'completion.completed', 'status': 'completed'}

    monkeypatch.setattr("service.file_extraction_agent.manager.build_qa_model", fake_build_qa_model)
    monkeypatch.setattr("service.file_extraction_agent.manager.stream_completion_events", fake_stream_completion_events)

    manager = CompletionManager()
    stream = manager.create(
        completion_id="cmp_race",
        resource_path=resource_path,
        messages=[DocumentQaMessage(role="user", content="问题")],
        model_config=ModelConfig(model_name="qa"),
    )

    assert manager.terminate("cmp_race") == {"id": "cmp_race", "status": "cancelling"}
    graph_can_complete.set()
    events = _frames(stream)

    terminal_events = [event for event in events if "completion." in event]
    assert terminal_events == [
        'event: completion.cancelled\ndata: {"type":"completion.cancelled","status":"cancelled"}\n\n'
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

    monkeypatch.setattr(model_module, "ChatOpenAI", FakeChatOpenAI)

    model = build_chat_model(
        ModelConfig(
            base_url="https://example.com/v1",
            api_key="key",
            model_name="qa",
        ),
        "qa",
    )

    attempts = model.model_call_attempts()
    assert [attempt.name for attempt in attempts] == [
        "responses_stream",
        "responses_invoke",
    ]
    assert [attempt.use_stream for attempt in attempts] == [True, False]
    assert [kwargs["use_responses_api"] for kwargs in captured] == [True, True]
    assert [kwargs["streaming"] for kwargs in captured] == [True, False]
    assert [kwargs["request_timeout"] for kwargs in captured] == [8.0, 8.0]


def test_build_chat_model_builds_chat_completions_transport_when_configured(monkeypatch):
    captured = []

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.append(kwargs)

    monkeypatch.setattr(model_module, "ChatOpenAI", FakeChatOpenAI)

    model = build_chat_model(
        ModelConfig(
            base_url="https://example.com/v1",
            api_key="key",
            model_name="qa",
            api_transport="chat_completions",
        ),
        "qa",
    )

    attempts = model.model_call_attempts()
    assert [attempt.name for attempt in attempts] == [
        "chat_completions_stream",
        "chat_completions_invoke",
    ]
    assert [attempt.use_stream for attempt in attempts] == [True, False]
    assert [kwargs["use_responses_api"] for kwargs in captured] == [False, False]
    assert [kwargs["streaming"] for kwargs in captured] == [True, False]


def test_build_chat_model_rejects_unknown_transport():
    with pytest.raises(ValueError, match="MODEL_API_TRANSPORT"):
        build_chat_model(
            ModelConfig(model_name="qa", api_transport="auto"),
            "qa",
        )


def test_normalize_model_config_rejects_untyped_dict_input():
    with pytest.raises(TypeError, match="unexpected model config type"):
        normalize_model_config({"model": "qa"})












def test_completion_manager_create_runs_graph_and_returns_sse(monkeypatch, resource_path):
    captured = {}

    def fake_build_qa_model(config):
        captured["config"] = config
        return "qa-model"

    def fake_stream_completion_events(*, qa_model, **kwargs):
        captured["has_completion_id"] = "completion_id" in kwargs
        captured["messages"] = kwargs["messages"]
        captured["model"] = qa_model
        yield {'type': 'completion.completed'}

    monkeypatch.setattr("service.file_extraction_agent.manager.build_qa_model", fake_build_qa_model)
    monkeypatch.setattr("service.file_extraction_agent.manager.stream_completion_events", fake_stream_completion_events)

    events = _frames(
        CompletionManager().create(
            completion_id="cmp_mgr",
            resource_path=resource_path,
            messages=[DocumentQaMessage(role="user", content="问题")],
            model_config=ModelConfig(model_name="qa"),
        )
    )

    assert events == ['event: completion.completed\ndata: {"type":"completion.completed"}\n\n']
    assert captured["has_completion_id"] is False
    assert captured["messages"][0].content == "问题"
    assert captured["model"] == "qa-model"
    assert captured["config"].model_name == "qa"


def test_completion_manager_create_registers_before_iteration_and_terminate_cancels(monkeypatch, resource_path):
    graph_called = threading.Event()

    def fake_build_qa_model(config):
        del config
        return "qa-model"

    def fake_stream_completion_events(*, qa_model, **kwargs):
        del qa_model
        graph_called.set()
        yield {'type': 'completion.completed'}

    manager = CompletionManager()
    monkeypatch.setattr("service.file_extraction_agent.manager.build_qa_model", fake_build_qa_model)
    monkeypatch.setattr("service.file_extraction_agent.manager.stream_completion_events", fake_stream_completion_events)

    stream = manager.create(
        completion_id="cmp_mgr_cancel",
        resource_path=resource_path,
        messages=[DocumentQaMessage(role="user", content="问题")],
        model_config=ModelConfig(model_name="qa"),
    )

    assert manager.terminate("cmp_mgr_cancel") == {"id": "cmp_mgr_cancel", "status": "cancelling"}
    assert _frames(stream) == [
        'event: completion.cancelled\ndata: {"type":"completion.cancelled","status":"cancelled"}\n\n'
    ]
    assert not graph_called.is_set()
    assert manager.terminate("cmp_mgr_cancel") == {"id": "cmp_mgr_cancel", "status": "not_found"}


def test_completion_manager_terminate_returns_not_found_for_unknown():
    manager = CompletionManager()
    assert manager.terminate("cmp_missing") == {"id": "cmp_missing", "status": "not_found"}


def test_completion_manager_get_status_returns_none_for_unknown():
    manager = CompletionManager()
    assert manager.get_status("cmp_missing") is None


def test_active_completion_owns_terminate_get_status_and_terminal_uniqueness():
    state = SimpleNamespace(
        completion_id="cmp_ac",
        document=SimpleNamespace(root=Path(".") / "nonexistent"),
        messages=[],
        run_options=RunOptions(),
    )
    runtime = ActiveCompletion("cmp_ac", "unused", object(), [])

    assert runtime.get_status() == "in_progress"
    assert runtime.terminate() == "cancelling"
    assert runtime.get_status() == "cancelling"
    assert runtime.terminate() == "cancelling"
    assert runtime.close_once("cancelled") is True
    assert runtime.get_status() == "cancelled"
    assert runtime.close_once("completed") is False


def test_qa_records_text_from_responses_api_content_blocks(tmp_path):
    message = AIMessage(
        content=[
            {"type": "reasoning", "summary": []},
            {"type": "text", "text": "I will inspect root. "},
            {"type": "function_call", "name": "ls", "arguments": '{"path":""}'},
        ],
        tool_calls=[
            {
                "id": "call-1",
                "name": "ls",
                "args": {"path": ""},
            }
        ],
    )

    event = manager_module._model_message_event(message)

    assert event["content"] == "I will inspect root. "





def test_qa_records_terminal_stop_message_as_final_answer(tmp_path):
    message = AIMessage(
        content="最终答案。",
        response_metadata={"finish_reason": "stop"},
    )

    event = manager_module._model_message_event(message)

    assert event["content"] == "最终答案。"
    assert event["is_final"] is True
    assert event["stop_signal"] == "stop"



def test_qa_records_model_message_content_and_tool_calls_without_reasoning(tmp_path):
    message = AIMessage(
        content="I will inspect the root listing while calling a tool.",
        additional_kwargs={"reasoning_content": "hidden reasoning must not be persisted"},
        tool_calls=[
            {
                "id": "call-1",
                "name": "ls",
                "args": {"path": ""},
            }
        ],
    )

    event = manager_module._model_message_event(message)

    assert event == {
        "type": "model_message",
        "content": "I will inspect the root listing while calling a tool.",
        "tool_call_count": 1,
        "tool_calls": [{"id": "call-1", "name": "ls", "args": {"path": ""}}],
        "is_final": False,
    }




def _without_seq(frame):
    import json
    event_line, data = frame.split("\ndata: ", 1)
    payload = json.loads(data)
    payload.pop("seq", None)
    return event_line + "\ndata: " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n\n"


def _frames(stream):
    return [_without_seq(frame) for frame in stream]
