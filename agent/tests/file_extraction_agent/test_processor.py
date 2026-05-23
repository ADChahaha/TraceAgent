from __future__ import annotations

import threading
import time

import pytest

from service.file_extraction_agent.impl import model_factory as model_factory_module
from service.file_extraction_agent.impl.model_factory import build_chat_model, normalize_model_config
from service.file_extraction_agent import processor as processor_module
from service.file_extraction_agent.processor import cancel_completion, create_completion_stream
from service.file_extraction_agent.schemas import ModelConfig


def test_create_completion_stream_builds_completion_input_and_runs_graph(monkeypatch):
    captured = {}

    def fake_build_resolution_model(config):
        captured["config"] = config
        return "resolution-model"

    def fake_run_completion_graph_stream(completion_input, resolution_model):
        captured["completion_id"] = completion_input.completion_id
        captured["documents"] = completion_input.documents
        captured["messages"] = completion_input.messages
        captured["model"] = resolution_model
        yield 'event: completion.completed\ndata: {"id":"cmp_123"}\n\n'

    monkeypatch.setattr("service.file_extraction_agent.processor.build_resolution_model", fake_build_resolution_model)
    monkeypatch.setattr("service.file_extraction_agent.processor.run_completion_graph_stream", fake_run_completion_graph_stream)

    events = list(
        create_completion_stream(
            completion_id="cmp_123",
            documents=[{"filename": "notice.html", "html": '<p id="p1">通知</p>'}],
            messages=[{"role": "user", "content": "问题"}],
            model_config=ModelConfig(resolution_model_name="resolution"),
        )
    )

    assert events == ['event: completion.completed\ndata: {"id":"cmp_123"}\n\n']
    assert captured["completion_id"] == "cmp_123"
    assert captured["documents"][0].filename == "notice.html"
    assert captured["messages"][0].content == "问题"
    assert captured["model"] == "resolution-model"


def test_create_completion_stream_validates_input_before_iteration(monkeypatch):
    called = False

    def fake_build_resolution_model(config):
        nonlocal called
        called = True
        return "resolution-model"

    monkeypatch.setattr("service.file_extraction_agent.processor.build_resolution_model", fake_build_resolution_model)

    with pytest.raises(ValueError, match="documents"):
        create_completion_stream(
            completion_id="cmp_123",
            documents=[],
            messages=[{"role": "user", "content": "问题"}],
            model_config=ModelConfig(resolution_model_name="resolution"),
        )

    assert called is False


def test_create_completion_stream_registers_active_completion_before_iteration(monkeypatch):
    graph_called = threading.Event()

    def fake_build_resolution_model(config):
        return "resolution-model"

    def fake_run_completion_graph_stream(completion_input, resolution_model):
        del completion_input, resolution_model
        graph_called.set()
        yield 'event: completion.completed\ndata: {"id":"cmp_early_cancel"}\n\n'

    monkeypatch.setattr("service.file_extraction_agent.processor.build_resolution_model", fake_build_resolution_model)
    monkeypatch.setattr("service.file_extraction_agent.processor.run_completion_graph_stream", fake_run_completion_graph_stream)

    stream = create_completion_stream(
        completion_id="cmp_early_cancel",
        documents=[{"filename": "notice.html", "html": '<p id="p1">通知</p>'}],
        messages=[{"role": "user", "content": "问题"}],
        model_config=ModelConfig(resolution_model_name="resolution"),
    )

    assert cancel_completion("cmp_early_cancel") == {"id": "cmp_early_cancel", "status": "cancelling"}
    assert list(stream) == [
        'event: completion.cancelled\ndata: {"id":"cmp_early_cancel","type":"completion.cancelled","status":"cancelled"}\n\n'
    ]
    assert not graph_called.is_set()
    assert cancel_completion("cmp_early_cancel") == {"id": "cmp_early_cancel", "status": "not_found"}


def test_create_completion_stream_cancel_does_not_wait_for_blocked_graph(monkeypatch):
    monkeypatch.setattr(processor_module, "_QUEUE_TIMEOUT_SECONDS", 10.0, raising=False)
    graph_started = threading.Event()
    release_graph = threading.Event()

    def fake_build_resolution_model(config):
        del config
        return "resolution-model"

    def fake_run_completion_graph_stream(completion_input, resolution_model):
        del completion_input, resolution_model
        graph_started.set()
        release_graph.wait(timeout=1.0)
        yield 'event: completion.completed\ndata: {"id":"cmp_blocked"}\n\n'

    monkeypatch.setattr("service.file_extraction_agent.processor.build_resolution_model", fake_build_resolution_model)
    monkeypatch.setattr("service.file_extraction_agent.processor.run_completion_graph_stream", fake_run_completion_graph_stream)

    stream = create_completion_stream(
        completion_id="cmp_blocked",
        documents=[{"filename": "notice.html", "html": '<p id="p1">通知</p>'}],
        messages=[{"role": "user", "content": "问题"}],
        model_config=ModelConfig(resolution_model_name="resolution"),
    )
    events: list[str] = []
    stream_done = threading.Event()

    def consume_stream():
        events.extend(list(stream))
        stream_done.set()

    consumer_thread = threading.Thread(target=consume_stream, daemon=True)
    consumer_thread.start()

    assert graph_started.wait(timeout=0.5)
    assert cancel_completion("cmp_blocked") == {"id": "cmp_blocked", "status": "cancelling"}
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
    assert cancel_completion("cmp_blocked") == {"id": "cmp_blocked", "status": "not_found"}


def test_create_completion_stream_flushes_committed_events_before_cancel(monkeypatch):
    second_event_reached_graph = threading.Event()
    release_graph = threading.Event()

    def fake_build_resolution_model(config):
        del config
        return "resolution-model"

    def fake_run_completion_graph_stream(completion_input, resolution_model):
        del completion_input, resolution_model
        yield 'event: model_message\ndata: {"type":"model_message","content":"first"}\n\n'
        second_event_reached_graph.set()
        yield 'event: tool_completed\ndata: {"type":"tool_completed","tool":"read"}\n\n'
        release_graph.wait(timeout=1.0)
        yield 'event: completion.completed\ndata: {"id":"cmp_flush","type":"completion.completed","status":"completed"}\n\n'

    monkeypatch.setattr("service.file_extraction_agent.processor.build_resolution_model", fake_build_resolution_model)
    monkeypatch.setattr("service.file_extraction_agent.processor.run_completion_graph_stream", fake_run_completion_graph_stream)

    stream = iter(
        create_completion_stream(
            completion_id="cmp_flush",
            documents=[{"filename": "notice.html", "html": '<p id="p1">通知</p>'}],
            messages=[{"role": "user", "content": "问题"}],
            model_config=ModelConfig(resolution_model_name="resolution"),
        )
    )

    first_event = next(stream)
    assert second_event_reached_graph.wait(timeout=0.5)
    time.sleep(0.02)
    assert cancel_completion("cmp_flush") == {"id": "cmp_flush", "status": "cancelling"}
    try:
        remaining_events = list(stream)
    finally:
        release_graph.set()

    assert first_event == 'event: model_message\ndata: {"type":"model_message","content":"first"}\n\n'
    assert remaining_events == [
        'event: tool_completed\ndata: {"type":"tool_completed","tool":"read"}\n\n',
        'event: completion.cancelled\ndata: {"id":"cmp_flush","type":"completion.cancelled","status":"cancelled"}\n\n',
    ]
    assert cancel_completion("cmp_flush") == {"id": "cmp_flush", "status": "not_found"}


def test_create_completion_stream_emits_only_one_terminal_event_when_cancel_races_completed(monkeypatch):
    graph_can_complete = threading.Event()

    def fake_build_resolution_model(config):
        del config
        return "resolution-model"

    def fake_run_completion_graph_stream(completion_input, resolution_model):
        del completion_input, resolution_model
        graph_can_complete.wait(timeout=1.0)
        yield 'event: completion.completed\ndata: {"id":"cmp_race","type":"completion.completed","status":"completed"}\n\n'

    monkeypatch.setattr("service.file_extraction_agent.processor.build_resolution_model", fake_build_resolution_model)
    monkeypatch.setattr("service.file_extraction_agent.processor.run_completion_graph_stream", fake_run_completion_graph_stream)

    stream = create_completion_stream(
        completion_id="cmp_race",
        documents=[{"filename": "notice.html", "html": '<p id="p1">通知</p>'}],
        messages=[{"role": "user", "content": "问题"}],
        model_config=ModelConfig(resolution_model_name="resolution"),
    )

    assert cancel_completion("cmp_race") == {"id": "cmp_race", "status": "cancelling"}
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
                'RESOLUTION_MODEL="resolution"',
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
    monkeypatch.setattr(model_factory_module, "_candidate_env_paths", lambda: [env_path])
    missing_cwd = tmp_path / "missing"
    missing_cwd.mkdir()
    monkeypatch.chdir(missing_cwd)
    for name in (
        "BASE_URL",
        "API_KEY",
        "OPENAI_API_KEY",
        "RESOLUTION_MODEL",
        "MODEL",
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
    assert config.resolution_model_name == "resolution"
    assert config.temperature == 0.1
    assert config.top_p == 0.9
    assert config.top_k == 40
    assert config.reasoning_effort == "high"
    assert config.max_retries == 8
    assert config.request_timeout == 120.0


def test_build_chat_model_builds_responses_stream_then_chat_fallbacks(monkeypatch):
    captured = []

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.append(kwargs)

    monkeypatch.setattr(model_factory_module, "ChatOpenAI", FakeChatOpenAI)

    model = build_chat_model(
        ModelConfig(
            base_url="https://example.com/v1",
            api_key="key",
            resolution_model_name="resolution",
        ),
        "resolution",
    )

    attempts = model.model_call_attempts()
    assert [attempt.name for attempt in attempts] == [
        "responses_stream",
        "chat_completions_stream",
        "responses_invoke",
        "chat_completions_invoke",
    ]
    assert [attempt.use_stream for attempt in attempts] == [True, True, False, False]
    assert [kwargs["use_responses_api"] for kwargs in captured] == [True, False, True, False]
    assert [kwargs["streaming"] for kwargs in captured] == [True, True, False, False]
    assert [kwargs["request_timeout"] for kwargs in captured] == [30.0, 30.0, 30.0, 30.0]


def test_normalize_model_config_rejects_unknown_model_fields():
    with pytest.raises(TypeError, match="unexpected keyword argument 'broad_model_name'"):
        normalize_model_config({"broad_model_name": "broad", "resolution_model_name": "resolution"})
