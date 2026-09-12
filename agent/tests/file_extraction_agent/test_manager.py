from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock
from tests.async_helpers import async_items, wait_event
from pathlib import Path
import time
from types import SimpleNamespace
import pytest
from langchain_core.messages import AIMessage, ToolMessage
from service.file_extraction_agent.core import model as model_module
from service.file_extraction_agent.core.model import build_chat_model, normalize_model_config
from service.file_extraction_agent import manager as manager_module
from service.file_extraction_agent import completion_runtime as runtime_module
from service.file_extraction_agent.completion_runtime import CompletionRuntime
from service.file_extraction_agent.manager import CompletionManager
from service.file_extraction_agent.schemas import DocumentQaMessage, ModelConfig, RunOptions


async def test_runtime_yields_event_objects_with_sequence(resource_path, monkeypatch):
    """运行时直接输出事件对象，传输编码由接口层负责。"""
    monkeypatch.setattr(
        runtime_module,
        "stream_completion_events",
        lambda **kwargs: async_items(
            [
                {"type": "model_message.done", "content": "你好\n世界"},
            ]
        ),
    )
    runtime = CompletionRuntime(resource_path, object(), [DocumentQaMessage(role="user", content="问题")])
    assert [item async for item in runtime.stream()] == [
        {"type": "completion.created", "status": "in_progress", "seq": 1},
        {"type": "model_message.done", "content": "你好\n世界", "seq": 2},
        {"type": "completion.completed", "status": "completed", "seq": 3},
    ]
    assert runtime._producer.done()


@pytest.mark.parametrize("ending", ["completed", "failed", "cancelled"])
async def test_stream_numbers_messages_and_terminal_once(tmp_path, monkeypatch, ending, resource_path):
    import json

    manager = CompletionManager()

    async def messages(*args, **kwargs):
        yield AIMessage(content="答案", response_metadata={"finish_reason": "stop"})
        if ending == "failed":
            raise RuntimeError("provider failed")
        if ending == "cancelled":
            manager.terminate("cmp_seq")

    monkeypatch.setattr(manager_module, "build_qa_model", lambda config: object())
    monkeypatch.setattr(runtime_module, "run_qa_stream", messages)
    frames = [
        item
        async for item in manager.create(
            completion_id="cmp_seq",
            run_options=RunOptions(),
            workspace=resource_path,
            messages=[DocumentQaMessage(role="user", content="问题")],
        ).stream()
    ]
    events = frames
    assert all(("id" not in event and "completion_id" not in event for event in events))
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    terminal = [e for e in events if e["type"] in {"completion.completed", "completion.failed"}]
    assert len(terminal) == (0 if ending == "cancelled" else 1)
    if terminal:
        assert terminal[0]["type"] == f"completion.{ending}"
    assert not any(e["type"] in {"completion.cancelled", "tool_failed"} for e in events)



async def test_completion_runtime_streams_without_manager(resource_path, monkeypatch):
    import json
    from service.file_extraction_agent import completion_runtime

    monkeypatch.setattr(
        completion_runtime,
        "run_qa_stream",
        lambda **kwargs: async_items(
            [AIMessage(content="回答", response_metadata={"finish_reason": "stop"})]
        ),
    )
    runtime = completion_runtime.CompletionRuntime(
        resource_path, object(), [DocumentQaMessage(role="user", content="问题")]
    )
    events = [item async for item in runtime.stream()]
    assert [event["type"] for event in events] == [
        "completion.created",
        "source_indexed",
        "model_message.done",
        "completion.completed",
    ]
    assert runtime._producer.done()
    assert [event["seq"] for event in events] == [1, 2, 3, 4]
    assert all(("id" not in event for event in events))


async def test_manager_keeps_id_outside_runtime_and_cleans_only_matching_entry(resource_path, monkeypatch):
    monkeypatch.setattr(manager_module, "build_qa_model", lambda config: object())
    monkeypatch.setattr(
        runtime_module,
        "run_qa_stream",
        lambda **kwargs: async_items(
            [AIMessage(content="回答", response_metadata={"finish_reason": "stop"})]
        ),
    )
    manager = CompletionManager()
    streams = {
        cid: manager.create(
            completion_id=cid,
            workspace=resource_path,
            messages=[DocumentQaMessage(role="user", content="问题")],
        )
        for cid in ("first", "second")
    }
    try:
        assert all((not hasattr(runtime, "completion_id") for runtime in manager._completions.values()))
        [item async for item in streams["first"].stream()]
        assert manager.get_status("first") is None
        assert manager.get_status("second")["status"] == "in_progress"
        assert manager.terminate("second")["status"] == "cancelling"
        [item async for item in streams["second"].stream()]
        assert manager.get_status("second") is None
    finally:
        for cid, stream in streams.items():
            manager.terminate(cid)
            stream.close()


async def test_startup_events_only_acknowledge_without_reading_documents(resource_path, monkeypatch):
    from service.file_extraction_agent.core.tools.workspace import DocumentFileTree

    def forbidden(*args, **kwargs):
        raise AssertionError("启动通知不应遍历或读取文档")

    monkeypatch.setattr(DocumentFileTree, "entries", forbidden)
    monkeypatch.setattr(DocumentFileTree, "read", forbidden)
    stream = runtime_module.stream_completion_events(
        workspace=resource_path,
        messages=[DocumentQaMessage(role="user", content="问题")],
        qa_model=object(),
    )
    try:
        source = await anext(stream)
        assert source == {"type": "source_indexed", "tool": "source_index", "result": {"ok": True}}
    finally:
        await stream.aclose()


async def test_runtime_cancel_interrupts_real_tools_and_skips_next_model(
    tmp_path, monkeypatch, resource_path, s3_store
):
    import json
    from unittest.mock import Mock, AsyncMock
    from service.file_extraction_agent.core.model import ConfiguredChatModel, ModelCallAttempt
    from service.file_extraction_agent.core import loop

    started, release = (asyncio.Event(), asyncio.Event())
    provider = Mock(spec=["bind_tools", "ainvoke"])
    provider.bind_tools.return_value = provider
    provider.ainvoke = AsyncMock()
    provider.ainvoke.side_effect = [
        AIMessage(
            content="读取",
            tool_calls=[
                {"id": "read-1", "name": "read", "args": {"path": "first"}},
                {"id": "read-2", "name": "read", "args": {"path": "second"}},
            ],
        )
    ]

    class Reader:
        name = "read"

        async def ainvoke(self, args):
            started.set()
            assert await wait_event(release, 2)
            return {"ok": True, "text": args["path"]}

    monkeypatch.setattr(loop, "build_tools", lambda state: [Reader()])
    monkeypatch.setattr(
        manager_module,
        "build_qa_model",
        lambda config: ConfiguredChatModel([ModelCallAttempt("test", provider, False)]),
    )
    manager = CompletionManager()
    stream = manager.create(
        completion_id="cmp_real_cancel",
        run_options=RunOptions(),
        workspace=resource_path,
        messages=[DocumentQaMessage(role="user", content="问题")],
    ).stream()
    frames = []
    done = asyncio.Event()

    async def consume():
        try:
            frames.extend([item async for item in stream])
        finally:
            done.set()

    thread = asyncio.create_task(consume())
    try:
        assert await wait_event(started, 1)
        assert manager.terminate("cmp_real_cancel")["status"] == "cancelling"
        assert await wait_event(done, 0.5)
    finally:
        release.set()
        await asyncio.wait_for(thread, 2)
    assert done.is_set()
    events = frames
    results = [event for event in events if event["type"] == "tool_completed"]
    assert results == []
    assert not any(e["type"] == "completion.cancelled" for e in events)
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    assert provider.ainvoke.call_count == 1
    assert _resource_exists(resource_path, s3_store)


def _resource_exists(resource_refs, s3_store) -> bool:
    from service.object_store import parse_resource_path

    documents_location = next(ref.location for ref in resource_refs if ref.type == "documents")
    bucket, _ = parse_resource_path(documents_location)
    return s3_store.get_object(bucket, "manifest.json") is not None


async def test_manager_wraps_messages_and_pairs_same_name_calls(tmp_path, monkeypatch, resource_path):
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
        async for item in runtime_module.stream_completion_events(
            workspace=resource_path,
            messages=[DocumentQaMessage(role="user", content="问题")],
            qa_model=object(),
        )
    ]
    assert [e["type"] for e in events] == [
        "source_indexed",
        "model_message.done",
        "tool_started",
        "tool_started",
        "tool_completed",
        "tool_failed",
        "model_message.done",
    ]
    results = [e for e in events if e["type"] in {"tool_completed", "tool_failed"}]
    assert [(e["tool_call_id"], e["args"]["path"]) for e in results] == [("a", "first"), ("b", "second")]
    assert events[-1]["is_final"] is True


async def test_graph_keeps_events_as_objects_until_stream_boundary(tmp_path, monkeypatch, resource_path):
    monkeypatch.setattr(
        runtime_module,
        "run_qa_stream",
        lambda *args, **kwargs: async_items(
            [AIMessage(content="完成", response_metadata={"finish_reason": "stop"})]
        ),
    )
    events = [
        item
        async for item in runtime_module.stream_completion_events(
            workspace=resource_path,
            messages=[DocumentQaMessage(role="user", content="问题")],
            qa_model=object(),
        )
    ]
    assert all((isinstance(event, dict) for event in events))
    assert [event["type"] for event in events] == [
        "source_indexed",
        "model_message.done",
    ]


async def test_stream_preserves_runtime_failure_with_special_characters(tmp_path, monkeypatch, resource_path):
    import json

    error = '失败：第一行\n第二行\t"引号"\\路径'

    def fail(*args, **kwargs):
        raise RuntimeError(error)

    monkeypatch.setattr(manager_module, "build_qa_model", lambda config: object())
    monkeypatch.setattr(runtime_module, "stream_completion_events", fail)
    frames = await _frames(
        CompletionManager().create(
            completion_id="cmp_error",
            run_options=RunOptions(),
            workspace=resource_path,
            messages=[DocumentQaMessage(role="user", content="问题")],
        ).stream()
    )
    assert len(frames) == 2
    assert frames[-1]["type"] == "completion.failed"
    assert frames[-1]["error_message"] == error


@pytest.mark.parametrize("marker", ["completed", "cancelled", "failed"])
async def test_stream_preserves_terminal_words_in_data(tmp_path, monkeypatch, marker, resource_path):
    import json

    ordinary = {"type": "model_message.done", "content": f"event: completion.{marker}"}
    terminal = {"type": "completion.completed", "status": "completed"}
    monkeypatch.setattr(manager_module, "build_qa_model", lambda config: object())
    monkeypatch.setattr(
        runtime_module, "stream_completion_events", lambda *a, **k: async_items([ordinary])
    )
    frames = await _frames(
        CompletionManager().create(
            completion_id="cmp_words",
            run_options=RunOptions(),
            workspace=resource_path,
            messages=[DocumentQaMessage(role="user", content="问题")],
        ).stream()
    )
    assert frames == [{"type": "completion.created", "status": "in_progress"}, ordinary, terminal]


async def test_create_completion_stream_builds_completion_input_and_runs_graph(monkeypatch, resource_path):
    captured = {}

    def fake_build_qa_model(config):
        captured["config"] = config
        return "qa-model"

    async def fake_stream_completion_events(*, qa_model, **kwargs):
        captured["has_completion_id"] = "completion_id" in kwargs
        captured["document_root"] = kwargs["workspace"]
        captured["messages"] = kwargs["messages"]
        captured["model"] = qa_model
        if False:
            yield {}

    monkeypatch.setattr("service.file_extraction_agent.manager.build_qa_model", fake_build_qa_model)
    monkeypatch.setattr(
        "service.file_extraction_agent.completion_runtime.stream_completion_events",
        fake_stream_completion_events,
    )
    manager = CompletionManager()
    events = await _frames(
        manager.create(
            completion_id="cmp_123",
            workspace=resource_path,
            messages=[DocumentQaMessage(role="user", content="问题")],
            model_config=ModelConfig(model_name="qa"),
        ).stream()
    )
    assert events == [{"type": "completion.created", "status": "in_progress"}, {"type": "completion.completed", "status": "completed"}]
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
    with pytest.raises(ValueError, match="workspace"):
        manager.create(
            completion_id="cmp_123",
            workspace="",
            messages=[DocumentQaMessage(role="user", content="问题")],
            model_config=ModelConfig(model_name="qa"),
        )
    assert called is False


async def test_create_completion_stream_registers_completion_runtime_before_iteration(
    monkeypatch, resource_path
):
    graph_called = asyncio.Event()

    def fake_build_qa_model(config):
        return "qa-model"

    async def fake_stream_completion_events(*, qa_model, **kwargs):
        del qa_model
        graph_called.set()
        if False:
            yield {}

    monkeypatch.setattr("service.file_extraction_agent.manager.build_qa_model", fake_build_qa_model)
    monkeypatch.setattr(
        "service.file_extraction_agent.completion_runtime.stream_completion_events",
        fake_stream_completion_events,
    )
    manager = CompletionManager()
    stream = manager.create(
        completion_id="cmp_early_cancel",
        workspace=resource_path,
        messages=[DocumentQaMessage(role="user", content="问题")],
        model_config=ModelConfig(model_name="qa"),
    ).stream()
    assert manager.terminate("cmp_early_cancel") == {"id": "cmp_early_cancel", "status": "cancelling"}
    assert await _frames(stream) == []
    assert not graph_called.is_set()
    assert manager.terminate("cmp_early_cancel") == {"id": "cmp_early_cancel", "status": "not_found"}


async def test_create_completion_stream_cancel_does_not_wait_for_blocked_graph(monkeypatch, resource_path):
    graph_started = asyncio.Event()
    release_graph = asyncio.Event()

    def fake_build_qa_model(config):
        del config
        return "qa-model"

    async def fake_stream_completion_events(*, qa_model, **kwargs):
        del qa_model
        graph_started.set()
        await wait_event(release_graph, timeout=1.0)
        if False:
            yield {}

    monkeypatch.setattr("service.file_extraction_agent.manager.build_qa_model", fake_build_qa_model)
    monkeypatch.setattr(
        "service.file_extraction_agent.completion_runtime.stream_completion_events",
        fake_stream_completion_events,
    )
    manager = CompletionManager()
    stream = manager.create(
        completion_id="cmp_blocked",
        workspace=resource_path,
        messages=[DocumentQaMessage(role="user", content="问题")],
        model_config=ModelConfig(model_name="qa"),
    ).stream()
    events: list[str] = []
    stream_done = asyncio.Event()

    async def consume_stream():
        events.extend(await _frames(stream))
        stream_done.set()

    consumer_thread = asyncio.create_task(consume_stream())
    assert await wait_event(graph_started, timeout=0.5)
    assert manager.terminate("cmp_blocked") == {"id": "cmp_blocked", "status": "cancelling"}
    started_at = time.monotonic()
    try:
        assert await wait_event(stream_done, timeout=0.25)
    finally:
        release_graph.set()
        await asyncio.wait_for(consumer_thread, 1.0)
    assert time.monotonic() - started_at < 0.25
    assert events == [{"type": "completion.created", "status": "in_progress"}]
    assert manager.terminate("cmp_blocked") == {"id": "cmp_blocked", "status": "not_found"}


async def test_create_completion_stream_discards_queued_events_after_cancel(monkeypatch, resource_path):
    second_event_reached_graph = asyncio.Event()
    release_graph = asyncio.Event()

    def fake_build_qa_model(config):
        del config
        return "qa-model"

    async def fake_stream_completion_events(*, qa_model, **kwargs):
        del qa_model
        yield {"type": "model_message.done", "content": "first"}
        second_event_reached_graph.set()
        yield {"type": "tool_completed", "tool": "read"}
        await wait_event(release_graph, timeout=1.0)
        if False:
            yield {}

    monkeypatch.setattr("service.file_extraction_agent.manager.build_qa_model", fake_build_qa_model)
    monkeypatch.setattr(
        "service.file_extraction_agent.completion_runtime.stream_completion_events",
        fake_stream_completion_events,
    )
    manager = CompletionManager()
    stream = aiter(
        manager.create(
            completion_id="cmp_flush",
            workspace=resource_path,
            messages=[DocumentQaMessage(role="user", content="问题")],
            model_config=ModelConfig(model_name="qa"),
        ).stream()
    )
    assert (await anext(stream))["type"] == "completion.created"
    first_event = _without_seq(await anext(stream))
    assert await wait_event(second_event_reached_graph, timeout=0.5)
    await asyncio.sleep(0.02)
    assert manager.terminate("cmp_flush") == {"id": "cmp_flush", "status": "cancelling"}
    try:
        remaining_events = await _frames(stream)
    finally:
        release_graph.set()
    assert first_event == {"type": "model_message.done", "content": "first"}
    assert remaining_events == []
    assert manager.terminate("cmp_flush") == {"id": "cmp_flush", "status": "not_found"}


async def test_should_stop_is_wired_to_cancel_requested(monkeypatch, resource_path):
    batch_running = asyncio.Event()
    release_batch = asyncio.Event()
    seen_should_stop = {"value": None}

    def fake_build_qa_model(config):
        del config
        return "qa-model"

    async def fake_stream_completion_events(*, qa_model, **kwargs):
        del qa_model
        seen_should_stop["value"] = kwargs.get("should_stop")
        batch_running.set()
        await wait_event(release_batch, timeout=1.0)
        if False:
            yield {}

    monkeypatch.setattr("service.file_extraction_agent.manager.build_qa_model", fake_build_qa_model)
    monkeypatch.setattr(
        "service.file_extraction_agent.completion_runtime.stream_completion_events",
        fake_stream_completion_events,
    )
    manager = CompletionManager()
    stream = manager.create(
        completion_id="cmp_ws",
        workspace=resource_path,
        messages=[DocumentQaMessage(role="user", content="问题")],
        model_config=ModelConfig(model_name="qa"),
    ).stream()
    stream_done = asyncio.Event()

    async def consume_stream():
        await _frames(stream)
        stream_done.set()

    consumer_thread = asyncio.create_task(consume_stream())
    assert await wait_event(batch_running, timeout=0.5)
    assert callable(seen_should_stop["value"])
    assert seen_should_stop["value"]() is False
    assert manager.terminate("cmp_ws") == {"id": "cmp_ws", "status": "cancelling"}
    assert seen_should_stop["value"]() is True
    release_batch.set()
    await asyncio.wait_for(consumer_thread, 1.0)
    assert stream_done.is_set() is True
    assert manager.terminate("cmp_ws") == {"id": "cmp_ws", "status": "not_found"}


async def test_terminate_interrupts_active_tool_batch(monkeypatch, resource_path):
    batch_running = asyncio.Event()
    release_batch = asyncio.Event()

    def fake_build_qa_model(config):
        del config
        return "qa-model"

    async def fake_stream_completion_events(*, qa_model, **kwargs):
        del qa_model
        yield {
            "type": "model_message.done",
            "content": "读取",
            "tool_calls": [{"id": "deferred-read", "name": "read", "args": {}}],
        }
        batch_running.set()
        await wait_event(release_batch, timeout=1.0)
        yield {"type": "tool_completed", "tool": "read", "tool_call_id": "deferred-read"}
        if False:
            yield {}

    monkeypatch.setattr("service.file_extraction_agent.manager.build_qa_model", fake_build_qa_model)
    monkeypatch.setattr(
        "service.file_extraction_agent.completion_runtime.stream_completion_events",
        fake_stream_completion_events,
    )
    manager = CompletionManager()
    stream = manager.create(
        completion_id="cmp_deferred",
        workspace=resource_path,
        messages=[DocumentQaMessage(role="user", content="问题")],
        model_config=ModelConfig(model_name="qa"),
    ).stream()
    events: list[str] = []
    stream_done = asyncio.Event()

    async def consume_stream():
        events.extend(await _frames(stream))
        stream_done.set()

    consumer_thread = asyncio.create_task(consume_stream())
    assert await wait_event(batch_running, timeout=0.5)
    assert manager.terminate("cmp_deferred") == {"id": "cmp_deferred", "status": "cancelling"}
    try:
        assert await wait_event(stream_done, timeout=0.5) is True
    finally:
        release_batch.set()
        await asyncio.wait_for(consumer_thread, 1.0)
    tool_events = [event for event in events if event["type"] == "tool_completed"]
    assert tool_events == []
    assert not any(e["type"] == "completion.cancelled" for e in events)
    assert manager.terminate("cmp_deferred") == {"id": "cmp_deferred", "status": "not_found"}


async def test_create_completion_stream_emits_only_one_terminal_event_when_cancel_races_completed(
    monkeypatch, resource_path
):
    graph_can_complete = asyncio.Event()

    def fake_build_qa_model(config):
        del config
        return "qa-model"

    async def fake_stream_completion_events(*, qa_model, **kwargs):
        del qa_model
        await wait_event(graph_can_complete, timeout=1.0)
        if False:
            yield {}

    monkeypatch.setattr("service.file_extraction_agent.manager.build_qa_model", fake_build_qa_model)
    monkeypatch.setattr(
        "service.file_extraction_agent.completion_runtime.stream_completion_events",
        fake_stream_completion_events,
    )
    manager = CompletionManager()
    stream = manager.create(
        completion_id="cmp_race",
        workspace=resource_path,
        messages=[DocumentQaMessage(role="user", content="问题")],
        model_config=ModelConfig(model_name="qa"),
    ).stream()
    assert manager.terminate("cmp_race") == {"id": "cmp_race", "status": "cancelling"}
    graph_can_complete.set()
    events = await _frames(stream)
    terminal_events = [event for event in events if event["type"].startswith("completion.")]
    assert terminal_events == []


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
        ModelConfig(base_url="https://example.com/v1", api_key="key", model_name="qa"), "qa"
    )
    attempts = model.model_call_attempts()
    assert [attempt.name for attempt in attempts] == ["responses_stream"]
    assert [attempt.use_stream for attempt in attempts] == [True]
    assert [kwargs["use_responses_api"] for kwargs in captured] == [True]
    assert [kwargs["streaming"] for kwargs in captured] == [True]
    assert [kwargs["timeout"] for kwargs in captured] == [8.0]


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
    assert [attempt.name for attempt in attempts] == ["chat_completions_stream"]
    assert [attempt.use_stream for attempt in attempts] == [True]
    assert [kwargs["use_responses_api"] for kwargs in captured] == [False]
    assert [kwargs["streaming"] for kwargs in captured] == [True]


def test_build_chat_model_rejects_unknown_transport():
    with pytest.raises(ValueError, match="MODEL_API_TRANSPORT"):
        build_chat_model(ModelConfig(model_name="qa", api_transport="auto"), "qa")


def test_normalize_model_config_rejects_untyped_dict_input():
    with pytest.raises(TypeError, match="unexpected model config type"):
        normalize_model_config({"model": "qa"})


async def test_completion_manager_create_runs_graph_and_returns_events(monkeypatch, resource_path):
    captured = {}

    def fake_build_qa_model(config):
        captured["config"] = config
        return "qa-model"

    async def fake_stream_completion_events(*, qa_model, **kwargs):
        captured["has_completion_id"] = "completion_id" in kwargs
        captured["messages"] = kwargs["messages"]
        captured["model"] = qa_model
        if False:
            yield {}

    monkeypatch.setattr("service.file_extraction_agent.manager.build_qa_model", fake_build_qa_model)
    monkeypatch.setattr(
        "service.file_extraction_agent.completion_runtime.stream_completion_events",
        fake_stream_completion_events,
    )
    events = await _frames(
        CompletionManager().create(
            completion_id="cmp_mgr",
            workspace=resource_path,
            messages=[DocumentQaMessage(role="user", content="问题")],
            model_config=ModelConfig(model_name="qa"),
        ).stream()
    )
    assert events == [{"type": "completion.created", "status": "in_progress"}, {"type": "completion.completed", "status": "completed"}]
    assert captured["has_completion_id"] is False
    assert captured["messages"][0].content == "问题"
    assert captured["model"] == "qa-model"
    assert captured["config"].model_name == "qa"


async def test_completion_manager_create_registers_before_iteration_and_terminate_cancels(
    monkeypatch, resource_path
):
    graph_called = asyncio.Event()

    def fake_build_qa_model(config):
        del config
        return "qa-model"

    async def fake_stream_completion_events(*, qa_model, **kwargs):
        del qa_model
        graph_called.set()
        if False:
            yield {}

    manager = CompletionManager()
    monkeypatch.setattr("service.file_extraction_agent.manager.build_qa_model", fake_build_qa_model)
    monkeypatch.setattr(
        "service.file_extraction_agent.completion_runtime.stream_completion_events",
        fake_stream_completion_events,
    )
    stream = manager.create(
        completion_id="cmp_mgr_cancel",
        workspace=resource_path,
        messages=[DocumentQaMessage(role="user", content="问题")],
        model_config=ModelConfig(model_name="qa"),
    ).stream()
    assert manager.terminate("cmp_mgr_cancel") == {"id": "cmp_mgr_cancel", "status": "cancelling"}
    assert await _frames(stream) == []
    assert not graph_called.is_set()
    assert manager.terminate("cmp_mgr_cancel") == {"id": "cmp_mgr_cancel", "status": "not_found"}


def test_completion_manager_terminate_returns_not_found_for_unknown():
    manager = CompletionManager()
    assert manager.terminate("cmp_missing") == {"id": "cmp_missing", "status": "not_found"}


def test_completion_manager_get_status_returns_none_for_unknown():
    manager = CompletionManager()
    assert manager.get_status("cmp_missing") is None


def test_runtime_cancel_flag_is_idempotent():
    runtime = CompletionRuntime("unused", object(), [])
    assert runtime.cancel_requested is False
    runtime.terminate()
    runtime.terminate()
    assert runtime.cancel_requested is True
    assert not any(hasattr(runtime, field) for field in ("status", "closed", "terminal_committed"))


def test_qa_records_text_from_responses_api_content_blocks(tmp_path):
    message = AIMessage(
        content=[
            {"type": "reasoning", "summary": []},
            {"type": "text", "text": "I will inspect root. "},
            {"type": "function_call", "name": "ls", "arguments": '{"path":""}'},
        ],
        tool_calls=[{"id": "call-1", "name": "ls", "args": {"path": ""}}],
    )
    event = runtime_module._model_message_event(message)
    assert event["content"] == "I will inspect root. "


def test_qa_records_terminal_stop_message_as_final_answer(tmp_path):
    message = AIMessage(content="最终答案。", response_metadata={"finish_reason": "stop"})
    event = runtime_module._model_message_event(message)
    assert event["content"] == "最终答案。"
    assert event["is_final"] is True
    assert event["stop_signal"] == "stop"


def test_qa_records_model_message_content_and_tool_calls_without_reasoning(tmp_path):
    message = AIMessage(
        content="I will inspect the root listing while calling a tool.",
        additional_kwargs={"reasoning_content": "hidden reasoning must not be persisted"},
        tool_calls=[{"id": "call-1", "name": "ls", "args": {"path": ""}}],
    )
    event = runtime_module._model_message_event(message)
    assert event == {
        "message_id": "",
        "type": "model_message.done",
        "content": "I will inspect the root listing while calling a tool.",
        "tool_call_count": 1,
        "tool_calls": [{"id": "call-1", "name": "ls", "args": {"path": ""}}],
        "is_final": False,
    }


async def test_unstarted_stream_close_removes_registration(resource_path, monkeypatch):
    """预检后客户端已断开时，尚未开始迭代也能清理注册项。"""
    monkeypatch.setattr(manager_module, "build_qa_model", lambda config: object())
    manager = CompletionManager()
    stream = manager.create(
        completion_id="early_close",
        workspace=resource_path,
        messages=[DocumentQaMessage(role="user", content="问题")],
    )
    stream.close()
    assert manager.get_status("early_close") is None
    assert [item async for item in stream.stream()] == []


async def test_disconnect_wakes_consumer_and_stops_producer(resource_path, monkeypatch):
    """断连立即唤醒消费者，旧流的断连回调不影响复用 ID 的新流。"""
    started = asyncio.Event()
    release = asyncio.Event()
    done = asyncio.Event()
    observed_stop = []

    async def blocked(**kwargs):
        started.set()
        try:
            await release.wait()
            if False:
                yield {}
        finally:
            observed_stop.append(kwargs["should_stop"]())

    monkeypatch.setattr(manager_module, "build_qa_model", lambda config: object())
    monkeypatch.setattr(runtime_module, "stream_completion_events", blocked)
    manager = CompletionManager()
    stream = manager.create(
        completion_id="disconnect",
        workspace=resource_path,
        messages=[DocumentQaMessage(role="user", content="问题")],
    )
    events = []

    async def consume():
        events.extend([item async for item in stream.stream()])
        done.set()

    consumer = asyncio.create_task(consume())
    try:
        assert await wait_event(started, 2)
        stream.close()
        assert await wait_event(done, 1)
        assert manager.get_status("disconnect") is None
        replacement = manager.create(
            completion_id="disconnect",
            workspace=resource_path,
            messages=[DocumentQaMessage(role="user", content="新问题")],
        )
        try:
            stream.close()
            assert manager.get_status("disconnect")["status"] == "in_progress"
        finally:
            replacement.close()
    finally:
        release.set()
        await asyncio.wait_for(consumer, 2)
    deadline = time.monotonic() + 2
    while not observed_stop and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    assert observed_stop == [True]


async def test_disconnect_before_iteration_does_not_start_producer(resource_path, monkeypatch):
    """RPC 注册回调后立即断开，首次迭代不得再创建生产协程。"""
    monkeypatch.setattr(manager_module, "build_qa_model", lambda config: object())
    manager = CompletionManager()
    stream = manager.create(
        completion_id="disconnect_early",
        workspace=resource_path,
        messages=[DocumentQaMessage(role="user", content="问题")],
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("disconnected stream must not start a producer")

    monkeypatch.setattr(runtime_module.CompletionRuntime, "_produce", forbidden)
    stream.close()
    assert [item async for item in stream.stream()] == []
    assert manager.get_status("disconnect_early") is None


def _without_seq(event):
    assert isinstance(event, dict)
    return {key: value for key, value in event.items() if key != "seq"}


async def _frames(stream):
    return [_without_seq(event) async for event in stream]
