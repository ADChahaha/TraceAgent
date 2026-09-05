from __future__ import annotations

from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest

from service.file_extraction_agent.core import model as model_module
from service.file_extraction_agent.core.model import build_chat_model, normalize_model_config
from service.file_extraction_agent import manager as manager_module
from service.file_extraction_agent.manager import (
    ActiveCompletion,
    CompletionManager,
    prepare_completion_state,
)
from service.file_extraction_agent.schemas import DocumentQaMessage, InputDocument, ModelConfig, RunOptions


def test_graph_keeps_events_as_objects_until_stream_boundary(tmp_path, monkeypatch):
    state = prepare_completion_state(
        completion_id="cmp_objects", workspace_root=tmp_path,
        documents=[InputDocument(filename="a.html", html="<p>真实正文</p>")],
        messages=[DocumentQaMessage(role="user", content="问题")],
    )
    monkeypatch.setattr(manager_module, "run_resolution_stream", lambda *args: iter([{"ok": True}]))
    events = list(manager_module.run_completion_graph_stream(state, object()))
    assert all(isinstance(event, dict) for event in events)
    assert [event["type"] for event in events] == [
        "completion.created", "source_indexed", "completion.completed",
    ]


def test_stream_encodes_runtime_failure_with_special_characters(tmp_path, monkeypatch):
    import json
    error = '失败：第一行\n第二行\t"引号"\\路径'

    def fail(*args, **kwargs):
        raise RuntimeError(error)

    monkeypatch.setattr(manager_module, "build_resolution_model", lambda config: object())
    monkeypatch.setattr(manager_module, "run_completion_graph_stream", fail)
    frames = list(CompletionManager().create(
        completion_id="cmp_error", run_options=RunOptions(workspace_root=str(tmp_path)),
        documents=[InputDocument(filename="a.html", html="<p>正文</p>")],
        messages=[DocumentQaMessage(role="user", content="问题")],
    ))
    assert len(frames) == 1
    event_line, data_line, _, _ = frames[0].split("\n")
    assert event_line == "event: completion.failed"
    assert json.loads(data_line.removeprefix("data: "))["error_message"] == error


@pytest.mark.parametrize("completion_id", ["..", ".", "../other", "a/b", "a\\b", "C:\\outside", "/outside"])
def test_prepare_rejects_unsafe_completion_id_before_materializing(tmp_path, monkeypatch, completion_id):
    calls = []
    monkeypatch.setattr(manager_module, "materialize_tree", lambda docs, root: calls.append(root))
    with pytest.raises(ValueError, match="completion_id"):
        prepare_completion_state(
            completion_id=completion_id, workspace_root=tmp_path,
            documents=[InputDocument(filename="a.html", html="<p>x</p>")],
            messages=[DocumentQaMessage(role="user", content="问题")],
        )
    assert not calls


def test_prepare_rejects_existing_workspace_without_overwriting(tmp_path):
    existing = tmp_path / "cmp_existing"
    existing.mkdir()
    marker = existing / "keep.md"
    marker.write_text("保留", encoding="utf-8")
    with pytest.raises(ValueError, match="workspace"):
        prepare_completion_state(
            completion_id="cmp_existing", workspace_root=tmp_path,
            documents=[InputDocument(filename="a.html", html="<p>x</p>")],
            messages=[DocumentQaMessage(role="user", content="问题")],
        )
    assert list(existing.iterdir()) == [marker]


def test_cleanup_rejects_workspace_outside_owned_parent(tmp_path, monkeypatch):
    removed = []
    state = SimpleNamespace(document=SimpleNamespace(root=tmp_path), workspace_parent=tmp_path / "owned")
    monkeypatch.setattr(manager_module.shutil, "rmtree", lambda *a, **k: removed.append(a))
    with pytest.raises(ValueError, match="workspace"):
        manager_module._cleanup_workspace(state)
    assert not removed


@pytest.mark.parametrize("marker", ["completed", "cancelled", "failed"])
def test_stream_preserves_terminal_words_in_data(tmp_path, monkeypatch, marker):
    import json
    ordinary = {"type": "model_message", "content": f"event: completion.{marker}"}
    terminal = {"type": "completion.completed", "status": "completed"}
    monkeypatch.setattr(manager_module, "build_resolution_model", lambda config: object())
    monkeypatch.setattr(manager_module, "run_completion_graph_stream", lambda *a, **k: iter([ordinary, terminal]))
    frames = list(CompletionManager().create(
        completion_id="cmp_words", run_options=RunOptions(workspace_root=str(tmp_path)),
        documents=[InputDocument(filename="a.html", html="<p>x</p>")],
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


def test_create_completion_stream_builds_completion_input_and_runs_graph(monkeypatch):
    captured = {}

    def fake_build_resolution_model(config):
        captured["config"] = config
        return "resolution-model"

    def fake_run_completion_graph_stream(state, resolution_model, **kwargs):
        captured["completion_id"] = state.completion_id
        captured["document_root"] = str(state.document.root)
        captured["messages"] = state.messages
        captured["model"] = resolution_model
        yield {'id': 'cmp_123', 'type': 'completion.completed'}

    monkeypatch.setattr("service.file_extraction_agent.manager.build_resolution_model", fake_build_resolution_model)
    monkeypatch.setattr("service.file_extraction_agent.manager.run_completion_graph_stream", fake_run_completion_graph_stream)

    manager = CompletionManager()
    events = list(
        manager.create(
            completion_id="cmp_123",
            documents=[InputDocument(filename="notice.html", html='<p id="p1">通知</p>')],
            messages=[DocumentQaMessage(role="user", content="问题")],
            model_config=ModelConfig(model_name="resolution"),
        )
    )

    assert events == ['event: completion.completed\ndata: {"id":"cmp_123","type":"completion.completed"}\n\n']
    assert captured["completion_id"] == "cmp_123"
    assert captured["document_root"].endswith("cmp_123")
    assert captured["messages"][0].content == "问题"
    assert captured["model"] == "resolution-model"


def test_create_completion_stream_validates_input_before_iteration(monkeypatch):
    called = False

    def fake_build_resolution_model(config):
        nonlocal called
        called = True
        return "resolution-model"

    monkeypatch.setattr("service.file_extraction_agent.manager.build_resolution_model", fake_build_resolution_model)

    manager = CompletionManager()
    with pytest.raises(ValueError, match="documents"):
        manager.create(
            completion_id="cmp_123",
            documents=[],
            messages=[DocumentQaMessage(role="user", content="问题")],
            model_config=ModelConfig(model_name="resolution"),
        )

    assert called is False


def test_create_completion_stream_registers_active_completion_before_iteration(monkeypatch):
    graph_called = threading.Event()

    def fake_build_resolution_model(config):
        return "resolution-model"

    def fake_run_completion_graph_stream(completion_input, resolution_model, **kwargs):
        del completion_input, resolution_model
        graph_called.set()
        yield {'id': 'cmp_early_cancel', 'type': 'completion.completed'}

    monkeypatch.setattr("service.file_extraction_agent.manager.build_resolution_model", fake_build_resolution_model)
    monkeypatch.setattr("service.file_extraction_agent.manager.run_completion_graph_stream", fake_run_completion_graph_stream)

    manager = CompletionManager()
    stream = manager.create(
        completion_id="cmp_early_cancel",
        documents=[InputDocument(filename="notice.html", html='<p id="p1">通知</p>')],
        messages=[DocumentQaMessage(role="user", content="问题")],
        model_config=ModelConfig(model_name="resolution"),
    )

    assert manager.terminate("cmp_early_cancel") == {"id": "cmp_early_cancel", "status": "cancelling"}
    assert list(stream) == [
        'event: completion.cancelled\ndata: {"id":"cmp_early_cancel","type":"completion.cancelled","status":"cancelled"}\n\n'
    ]
    assert not graph_called.is_set()
    assert manager.terminate("cmp_early_cancel") == {"id": "cmp_early_cancel", "status": "not_found"}


def test_create_completion_stream_cancel_does_not_wait_for_blocked_graph(monkeypatch):
    graph_started = threading.Event()
    release_graph = threading.Event()

    def fake_build_resolution_model(config):
        del config
        return "resolution-model"

    def fake_run_completion_graph_stream(completion_input, resolution_model, **kwargs):
        del completion_input, resolution_model
        graph_started.set()
        release_graph.wait(timeout=1.0)
        yield {'id': 'cmp_blocked', 'type': 'completion.completed'}

    monkeypatch.setattr("service.file_extraction_agent.manager.build_resolution_model", fake_build_resolution_model)
    monkeypatch.setattr("service.file_extraction_agent.manager.run_completion_graph_stream", fake_run_completion_graph_stream)

    manager = CompletionManager()
    stream = manager.create(
        completion_id="cmp_blocked",
        documents=[InputDocument(filename="notice.html", html='<p id="p1">通知</p>')],
        messages=[DocumentQaMessage(role="user", content="问题")],
        model_config=ModelConfig(model_name="resolution"),
    )
    events: list[str] = []
    stream_done = threading.Event()

    def consume_stream():
        events.extend(list(stream))
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
        'event: completion.cancelled\ndata: {"id":"cmp_blocked","type":"completion.cancelled","status":"cancelled"}\n\n'
    ]
    assert manager.terminate("cmp_blocked") == {"id": "cmp_blocked", "status": "not_found"}


def test_create_completion_stream_flushes_committed_events_before_cancel(monkeypatch):
    second_event_reached_graph = threading.Event()
    release_graph = threading.Event()

    def fake_build_resolution_model(config):
        del config
        return "resolution-model"

    def fake_run_completion_graph_stream(completion_input, resolution_model, **kwargs):
        del completion_input, resolution_model
        yield {'type': 'model_message', 'content': 'first'}
        second_event_reached_graph.set()
        yield {'type': 'tool_completed', 'tool': 'read'}
        release_graph.wait(timeout=1.0)
        yield {'id': 'cmp_flush', 'type': 'completion.completed', 'status': 'completed'}

    monkeypatch.setattr("service.file_extraction_agent.manager.build_resolution_model", fake_build_resolution_model)
    monkeypatch.setattr("service.file_extraction_agent.manager.run_completion_graph_stream", fake_run_completion_graph_stream)

    manager = CompletionManager()
    stream = iter(
        manager.create(
            completion_id="cmp_flush",
            documents=[InputDocument(filename="notice.html", html='<p id="p1">通知</p>')],
            messages=[DocumentQaMessage(role="user", content="问题")],
            model_config=ModelConfig(model_name="resolution"),
        )
    )

    first_event = next(stream)
    assert second_event_reached_graph.wait(timeout=0.5)
    time.sleep(0.02)
    assert manager.terminate("cmp_flush") == {"id": "cmp_flush", "status": "cancelling"}
    try:
        remaining_events = list(stream)
    finally:
        release_graph.set()

    assert first_event == 'event: model_message\ndata: {"type":"model_message","content":"first"}\n\n'
    assert remaining_events == [
        'event: tool_completed\ndata: {"type":"tool_completed","tool":"read"}\n\n',
        'event: completion.cancelled\ndata: {"id":"cmp_flush","type":"completion.cancelled","status":"cancelled"}\n\n',
    ]
    assert manager.terminate("cmp_flush") == {"id": "cmp_flush", "status": "not_found"}


def test_should_stop_is_wired_to_cancel_requested(monkeypatch):
    batch_running = threading.Event()
    release_batch = threading.Event()
    seen_should_stop = {"value": None}

    def fake_build_resolution_model(config):
        del config
        return "resolution-model"

    def fake_run_completion_graph_stream(state, resolution_model, **kwargs):
        del state, resolution_model
        seen_should_stop["value"] = kwargs.get("should_stop")
        batch_running.set()
        release_batch.wait(timeout=1.0)
        yield {'id': 'cmp_ws', 'type': 'completion.completed', 'status': 'completed'}

    monkeypatch.setattr("service.file_extraction_agent.manager.build_resolution_model", fake_build_resolution_model)
    monkeypatch.setattr("service.file_extraction_agent.manager.run_completion_graph_stream", fake_run_completion_graph_stream)

    manager = CompletionManager()
    stream = manager.create(
        completion_id="cmp_ws",
        documents=[InputDocument(filename="notice.html", html='<p id="p1">通知</p>')],
        messages=[DocumentQaMessage(role="user", content="问题")],
        model_config=ModelConfig(model_name="resolution"),
    )
    stream_done = threading.Event()

    def consume_stream():
        list(stream)
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


def test_terminate_defers_cancel_until_active_tool_batch_settles(monkeypatch):
    batch_running = threading.Event()
    release_batch = threading.Event()

    def fake_build_resolution_model(config):
        del config
        return "resolution-model"

    def fake_run_completion_graph_stream(state, resolution_model, **kwargs):
        del resolution_model
        with state.events_lock:
            state.tool_batch_active = True
        batch_running.set()
        release_batch.wait(timeout=1.0)
        yield {'id': 'cmp_deferred', 'type': 'tool_completed', 'tool': 'read'}
        with state.events_lock:
            state.tool_batch_active = False
        yield {'id': 'cmp_deferred', 'type': 'completion.cancelled', 'status': 'cancelled'}

    monkeypatch.setattr("service.file_extraction_agent.manager.build_resolution_model", fake_build_resolution_model)
    monkeypatch.setattr("service.file_extraction_agent.manager.run_completion_graph_stream", fake_run_completion_graph_stream)

    manager = CompletionManager()
    stream = manager.create(
        completion_id="cmp_deferred",
        documents=[InputDocument(filename="notice.html", html='<p id="p1">通知</p>')],
        messages=[DocumentQaMessage(role="user", content="问题")],
        model_config=ModelConfig(model_name="resolution"),
    )
    events: list[str] = []
    stream_done = threading.Event()

    def consume_stream():
        events.extend(list(stream))
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
        'event: tool_completed\ndata: {"id":"cmp_deferred","type":"tool_completed","tool":"read"}\n\n'
    ]
    assert events[-1] == (
        'event: completion.cancelled\ndata: {"id":"cmp_deferred","type":"completion.cancelled","status":"cancelled"}\n\n'
    )
    assert manager.terminate("cmp_deferred") == {"id": "cmp_deferred", "status": "not_found"}
    graph_can_complete = threading.Event()

    def fake_build_resolution_model(config):
        del config
        return "resolution-model"

    def fake_run_completion_graph_stream(completion_input, resolution_model, **kwargs):
        del completion_input, resolution_model
        graph_can_complete.wait(timeout=1.0)
        yield {'id': 'cmp_race', 'type': 'completion.completed', 'status': 'completed'}

    monkeypatch.setattr("service.file_extraction_agent.manager.build_resolution_model", fake_build_resolution_model)
    monkeypatch.setattr("service.file_extraction_agent.manager.run_completion_graph_stream", fake_run_completion_graph_stream)

    manager = CompletionManager()
    stream = manager.create(
        completion_id="cmp_race",
        documents=[InputDocument(filename="notice.html", html='<p id="p1">通知</p>')],
        messages=[DocumentQaMessage(role="user", content="问题")],
        model_config=ModelConfig(model_name="resolution"),
    )

    assert manager.terminate("cmp_race") == {"id": "cmp_race", "status": "cancelling"}
    graph_can_complete.set()
    events = list(stream)

    terminal_events = [event for event in events if "completion." in event]
    assert terminal_events == [
        'event: completion.cancelled\ndata: {"id":"cmp_race","type":"completion.cancelled","status":"cancelled"}\n\n'
    ]


def test_normalize_model_config_loads_default_env_file(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                'BASE_URL="https://example.com/v1"',
                'OPENAI_API_KEY="key"',
                'MODEL="resolution"',
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
    assert config.model_name == "resolution"
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
            model_name="resolution",
        ),
        "resolution",
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
            model_name="resolution",
            api_transport="chat_completions",
        ),
        "resolution",
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
            ModelConfig(model_name="resolution", api_transport="auto"),
            "resolution",
        )


def test_normalize_model_config_rejects_untyped_dict_input():
    with pytest.raises(TypeError, match="unexpected model config type"):
        normalize_model_config({"model": "resolution"})


def test_prepare_completion_state_accepts_documents_and_append_only_messages(tmp_path):
    state = prepare_completion_state(
        completion_id="cmp_123",
        documents=[InputDocument(filename="notice.html", html='<p id="p1">正文</p>')],
        messages=[DocumentQaMessage(role="user", content="这份文件说了什么？")],
        workspace_root=tmp_path,
    )

    assert state.completion_id == "cmp_123"
    assert state.messages[0].content == "这份文件说了什么？"
    assert not hasattr(state, "memory")
    assert state.document.root == tmp_path / "cmp_123"


def test_prepare_completion_state_rejects_memory_argument(tmp_path):
    with pytest.raises(TypeError, match="memory"):
        prepare_completion_state(
            completion_id="cmp_123",
            documents=[InputDocument(filename="notice.html", html='<p id="p1">正文</p>')],
            messages=[DocumentQaMessage(role="user", content="问题")],
            memory={"prior_answers": ["会破坏 append-only prompt cache"]},
            workspace_root=tmp_path,
        )


def test_prepare_completion_state_rejects_missing_documents_or_messages(tmp_path):
    with pytest.raises(ValueError, match="documents"):
        prepare_completion_state(
            completion_id="cmp_123",
            documents=[],
            messages=[DocumentQaMessage(role="user", content="问题")],
            workspace_root=tmp_path,
        )
    with pytest.raises(ValueError, match="messages"):
        prepare_completion_state(
            completion_id="cmp_123",
            documents=[InputDocument(filename="notice.html", html='<p id="p1">正文</p>')],
            messages=[],
            workspace_root=tmp_path,
        )


def test_prepare_completion_state_rejects_document_without_filename_or_html(tmp_path):
    with pytest.raises(ValueError, match="filename"):
        prepare_completion_state(
            completion_id="cmp_123",
            documents=[InputDocument(filename="", html='<p id="p1">正文</p>')],
            messages=[DocumentQaMessage(role="user", content="问题")],
            workspace_root=tmp_path,
        )
    with pytest.raises(ValueError, match="html"):
        prepare_completion_state(
            completion_id="cmp_123",
            documents=[InputDocument(filename="notice.html", html="")],
            messages=[DocumentQaMessage(role="user", content="问题")],
            workspace_root=tmp_path,
        )


def test_prepare_completion_state_requires_completion_id(tmp_path):
    with pytest.raises(ValueError, match="completion_id"):
        prepare_completion_state(
            completion_id="",
            documents=[InputDocument(filename="notice.html", html='<p id="p1">正文</p>')],
            messages=[DocumentQaMessage(role="user", content="问题")],
            workspace_root=tmp_path,
        )


def test_completion_manager_create_runs_graph_and_returns_sse(monkeypatch):
    captured = {}

    def fake_build_resolution_model(config):
        captured["config"] = config
        return "resolution-model"

    def fake_run_completion_graph_stream(state, resolution_model, **kwargs):
        captured["completion_id"] = state.completion_id
        captured["messages"] = state.messages
        captured["model"] = resolution_model
        yield {'id': 'cmp_mgr', 'type': 'completion.completed'}

    monkeypatch.setattr("service.file_extraction_agent.manager.build_resolution_model", fake_build_resolution_model)
    monkeypatch.setattr("service.file_extraction_agent.manager.run_completion_graph_stream", fake_run_completion_graph_stream)

    events = list(
        CompletionManager().create(
            completion_id="cmp_mgr",
            documents=[InputDocument(filename="notice.html", html='<p id="p1">通知</p>')],
            messages=[DocumentQaMessage(role="user", content="问题")],
            model_config=ModelConfig(model_name="resolution"),
        )
    )

    assert events == ['event: completion.completed\ndata: {"id":"cmp_mgr","type":"completion.completed"}\n\n']
    assert captured["completion_id"] == "cmp_mgr"
    assert captured["messages"][0].content == "问题"
    assert captured["model"] == "resolution-model"
    assert captured["config"].model_name == "resolution"


def test_completion_manager_create_registers_before_iteration_and_terminate_cancels(monkeypatch):
    graph_called = threading.Event()

    def fake_build_resolution_model(config):
        del config
        return "resolution-model"

    def fake_run_completion_graph_stream(state, resolution_model, **kwargs):
        del state, resolution_model
        graph_called.set()
        yield {'id': 'cmp_mgr_cancel', 'type': 'completion.completed'}

    manager = CompletionManager()
    monkeypatch.setattr("service.file_extraction_agent.manager.build_resolution_model", fake_build_resolution_model)
    monkeypatch.setattr("service.file_extraction_agent.manager.run_completion_graph_stream", fake_run_completion_graph_stream)

    stream = manager.create(
        completion_id="cmp_mgr_cancel",
        documents=[InputDocument(filename="notice.html", html='<p id="p1">通知</p>')],
        messages=[DocumentQaMessage(role="user", content="问题")],
        model_config=ModelConfig(model_name="resolution"),
    )

    assert manager.terminate("cmp_mgr_cancel") == {"id": "cmp_mgr_cancel", "status": "cancelling"}
    assert list(stream) == [
        'event: completion.cancelled\ndata: {"id":"cmp_mgr_cancel","type":"completion.cancelled","status":"cancelled"}\n\n'
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
    runtime = ActiveCompletion("cmp_ac", state, object())

    assert runtime.get_status() == "in_progress"
    assert runtime.terminate() == "cancelling"
    assert runtime.get_status() == "cancelling"
    assert runtime.terminate() == "cancelling"
    assert runtime.close_once("cancelled") is True
    assert runtime.get_status() == "cancelled"
    assert runtime.close_once("completed") is False
