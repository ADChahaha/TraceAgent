"""真实 SQLite 与可控事件流验证会话恢复、取消和事务边界。"""

import asyncio
import copy

import pytest

from backend.core.config import BackendSettings
from backend.core.db import ThreadLocalDatabase, initialize_database
from backend.services.session_registry import SessionRegistry
from backend.services.session_history import build_snapshot
from backend.services.errors import ConflictError


class FakeCall:
    def __init__(self):
        self.events = asyncio.Queue()
        self.cancelled = False

    def cancel(self):
        self.cancelled = True
        self.events.put_nowait(None)

    def __aiter__(self):
        return self

    async def __anext__(self):
        event = await self.events.get()
        if event is None:
            raise StopAsyncIteration
        return event


class FakeAgent:
    def __init__(self):
        self.calls = []
        self.requests = []
        self.created = asyncio.Queue()

    async def prepare_resources(self, files):
        return [{"type": "documents", "location": "s3://test/documents.zip"}]

    def chat_completion(self, **request):
        call = FakeCall()
        self.requests.append(copy.deepcopy(request))
        self.calls.append(call)
        self.created.put_nowait(call)
        return call


async def setup(tmp_path, **overrides):
    settings = BackendSettings(database_path=tmp_path / "sessions.sqlite3", **overrides)
    database = ThreadLocalDatabase(settings.database_path)
    initialize_database(database.connect())
    agent = FakeAgent()
    registry = SessionRegistry(database=database, agent_client=agent, settings=settings)
    await registry.start()
    return registry, database, agent


async def next_type(subscription, expected):
    while True:
        event = await asyncio.wait_for(subscription.receive(), 2)
        if event["type"] == expected:
            return event


async def finish(call, manager, turn_id, text="回答"):
    context = await manager.attach()
    await call.events.put({"type": "model_message.done", "seq": 1, "message_id": "m1", "content": text})
    await call.events.put({"type": "completion.completed", "seq": 2})
    await next_type(context.subscription, "turn.completed")
    await manager.detach(context.subscription.id)


def test_detach_keeps_execution_and_resume_merges_history(tmp_path):
    async def scenario():
        registry, db, agent = await setup(tmp_path)
        try:
            manager, first = await registry.complete(content="第一问")
            call = await asyncio.wait_for(agent.created.get(), 2)
            await manager.detach(first.subscription.id)
            assert not call.cancelled
            await finish(call, manager, first.turn_id)
            assert manager.current_turn_state is None
            manager2, second = await registry.complete(session_id=manager.session_id, content="第二问")
            assert manager2 is manager
            call2 = await asyncio.wait_for(agent.created.get(), 2)
            await call2.events.put({"type": "model_message.delta", "seq": 1, "message_id": "m2", "delta": "半个回答"})
            await next_type(second.subscription, "model_message.delta")
            resumed = await manager.attach()
            snapshot = await build_snapshot(db, resumed)
            assert len(snapshot["state"]["turns"]) == 2
            assert snapshot["state"]["turns"][0]["status"] == "completed"
            assert snapshot["state"]["turns"][1]["items"][-1]["text"] == "半个回答"
            assert agent.requests[1]["messages"] == [
                {"role": "user", "content": "第一问", "tool_calls_json": "[]"},
                {"role": "assistant", "content": "回答", "tool_calls_json": "[]"},
                {"role": "user", "content": "第二问", "tool_calls_json": "[]"},
            ]
        finally:
            await registry.close()
            db.close()
    asyncio.run(scenario())


def test_attach_boundary_survives_completion_and_next_turn(tmp_path):
    async def scenario():
        registry, db, agent = await setup(tmp_path)
        try:
            manager, first = await registry.complete(content="问题")
            call = await agent.created.get()
            boundary = await manager.attach()
            await finish(call, manager, first.turn_id)
            _, second = await registry.complete(session_id=manager.session_id, content="新问题")
            snapshot = await build_snapshot(db, boundary)
            assert len(snapshot["state"]["turns"]) == 1
            assert snapshot["state"]["turns"][0]["status"] != "completed"
            assert snapshot["state"]["active_turn_id"] == first.turn_id
            await next_type(boundary.subscription, "turn.completed")
            event = await next_type(boundary.subscription, "turn.created")
            assert event["turn_id"] == second.turn_id
        finally:
            await registry.close()
            db.close()
    asyncio.run(scenario())


def test_cancel_rejects_late_event_and_does_not_cancel_new_turn(tmp_path):
    async def scenario():
        registry, db, agent = await setup(tmp_path)
        try:
            manager, first = await registry.complete(content="旧问题")
            call = await agent.created.get()
            old_runtime = manager.runtimes[first.turn_id]
            assert (await manager.cancel(first.turn_id))["status"] == "cancelled"
            assert call.cancelled
            _, second = await registry.complete(session_id=manager.session_id, content="新问题")
            new_call = await agent.created.get()
            await manager.agent_event(first.turn_id, old_runtime.generation,
                                      {"type": "model_message.done", "message_id": "late", "content": "迟到"})
            assert (await manager.cancel(first.turn_id))["status"] == "cancelled"
            assert not new_call.cancelled
            assert manager.active_turn_id == second.turn_id
            rows = db.connect().execute("SELECT content FROM chat_messages").fetchall()
            assert "迟到" not in [row[0] for row in rows]
        finally:
            await registry.close()
            db.close()
    asyncio.run(scenario())


def test_concurrent_create_has_one_active_turn_and_one_manager(tmp_path):
    async def scenario():
        registry, db, agent = await setup(tmp_path)
        try:
            manager, first = await registry.complete(content="问题")
            managers = await asyncio.gather(*(registry.get_or_load(manager.session_id) for _ in range(8)))
            assert all(item is manager for item in managers)
            with pytest.raises(ConflictError):
                await registry.complete(session_id=manager.session_id, content="并发问题")
            assert db.connect().execute("SELECT COUNT(*) FROM chat_turns").fetchone()[0] == 1
        finally:
            await registry.close()
            db.close()
    asyncio.run(scenario())


def test_completion_has_no_request_deduplication(tmp_path):
    from backend.routes.chat import CompletionInput
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        CompletionInput(content="问题", request_id="removed")

    async def scenario():
        registry, db, agent = await setup(tmp_path)
        try:
            first, _ = await registry.complete(content="问题")
            second, _ = await registry.complete(content="问题")
            assert first.session_id != second.session_id
            rows = db.connect().execute(
                "SELECT payload_json FROM chat_events WHERE event_type='turn.created'"
            ).fetchall()
            assert len(rows) == 2
            assert all(row["payload_json"] == "{}" for row in rows)
        finally:
            await registry.close()
            db.close()
    asyncio.run(scenario())



def test_cancelled_request_stops_acceptance(tmp_path, monkeypatch):
    async def scenario():
        registry, db, agent = await setup(tmp_path)
        entered, cancelled = asyncio.Event(), asyncio.Event()

        class BlockedCreationLock:
            async def __aenter__(self):
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()

            async def __aexit__(self, *args):
                pass

        original_lock = registry.creation_lock
        monkeypatch.setattr(registry, "creation_lock", BlockedCreationLock())
        request = asyncio.create_task(registry.complete(content="问题"))
        try:
            await entered.wait()
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request
            assert cancelled.is_set()
            assert db.connect().execute("SELECT COUNT(*) FROM chat_turns").fetchone()[0] == 0
        finally:
            registry.creation_lock = original_lock
            await registry.close()
            db.close()
    asyncio.run(scenario())



def test_tool_group_is_atomic_and_next_history_uses_original_ids(tmp_path):
    async def scenario():
        registry, db, agent = await setup(tmp_path)
        try:
            manager, context = await registry.complete(content="读两个位置")
            call = await agent.created.get()
            await call.events.put({"type": "model_message.done", "seq": 1, "message_id": "tools", "content": "查询",
                "tool_calls": [{"id": "a", "name": "read", "args_json": "{}"}, {"id": "b", "name": "read", "args_json": "{}"}]})
            await next_type(context.subscription, "model_message.done")
            await call.events.put({"type": "tool_completed", "seq": 2, "tool_call_id": "b", "tool": "read", "result_json": '{"value":2}'})
            await next_type(context.subscription, "tool_completed")
            assert db.connect().execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0] == 1
            await call.events.put({"type": "tool_failed", "seq": 3, "tool_call_id": "a", "tool": "read", "result_json": '{"error":"missing"}'})
            await next_type(context.subscription, "tool_failed")
            rows = db.connect().execute("SELECT role,tool_call_id FROM chat_messages ORDER BY sequence").fetchall()
            assert [tuple(row) for row in rows] == [("user", None), ("assistant", None), ("tool", "a"), ("tool", "b")]
            await call.events.put({"type": "completion.completed", "seq": 4})
            await next_type(context.subscription, "turn.completed")
        finally:
            await registry.close()
            db.close()
    asyncio.run(scenario())


def test_tool_write_failure_rolls_back_group_and_process_event(tmp_path):
    async def scenario():
        from backend.services.subscription import SubscriptionClosed
        registry, db, agent = await setup(tmp_path)
        try:
            manager, context = await registry.complete(content="问题")
            call = await agent.created.get()
            await call.events.put({"type": "model_message.done", "seq": 1, "message_id": "tools", "content": "查询",
                                   "tool_calls": [{"id": "a", "name": "read", "args_json": "{}"}]})
            await next_type(context.subscription, "model_message.done")
            db.connect().execute("CREATE TRIGGER reject_tool BEFORE INSERT ON chat_messages WHEN NEW.role='tool' BEGIN SELECT RAISE(ABORT, 'injected'); END")
            db.connect().commit()
            await call.events.put({"type": "tool_completed", "seq": 2, "tool_call_id": "a", "tool": "read", "result_json": "{}"})
            with pytest.raises(SubscriptionClosed):
                await next_type(context.subscription, "tool_completed")
            assert db.connect().execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0] == 1
            assert db.connect().execute("SELECT COUNT(*) FROM chat_events WHERE event_type='tool_completed'").fetchone()[0] == 0
            assert manager.broken
        finally:
            await registry.close()
            db.close()
    asyncio.run(scenario())


def test_idle_unload_and_cold_resume_do_not_keep_history_in_manager(tmp_path):
    async def scenario():
        registry, db, agent = await setup(tmp_path)
        try:
            manager, first = await registry.complete(content="问题")
            call = await agent.created.get()
            await manager.detach(first.subscription.id)
            manager.last_activity = 0
            await registry.evict_idle()
            assert registry.managers[manager.session_id] is manager
            await finish(call, manager, first.turn_id)
            tasks = [runtime.task for runtime in manager.runtimes.values()]
            await asyncio.gather(*tasks)
            manager.last_activity = 0
            await registry.evict_idle()
            assert manager.session_id not in registry.managers
            loaded = await registry.get_or_load(manager.session_id)
            assert loaded is not manager and loaded.current_turn_state is None
            snapshot = await build_snapshot(db, await loaded.attach())
            assert snapshot["state"]["turns"][0]["status"] == "completed"
        finally:
            await registry.close()
            db.close()
    asyncio.run(scenario())


def test_startup_marks_orphan_execution_failed_without_restarting_agent(tmp_path):
    async def scenario():
        from backend.crud import crud
        registry, db, agent = await setup(tmp_path)
        await registry.close()
        crud.create_session(db.connect(), session_id="orphan", status="running", now="now")
        crud.create_turn(db.connect(), session_id="orphan", turn_id="lost", status="in_progress", now="now")
        crud.update_session(db.connect(), session_id="orphan", now="now", active_turn_id="lost")
        registry = SessionRegistry(database=db, agent_client=agent, settings=registry.settings)
        await registry.start()
        try:
            manager = await registry.get_or_load("orphan")
            snapshot = await build_snapshot(db, await manager.attach())
            assert snapshot["state"]["active_turn_id"] is None
            assert snapshot["state"]["turns"][0]["status"] == "failed"
            assert snapshot["state"]["turns"][0]["error"] == "backend_restarted"
            assert agent.calls == []
        finally:
            await registry.close()
            db.close()
    asyncio.run(scenario())


def test_retry_marks_failed_attempt_and_terminal_clears_retry_state(tmp_path):
    async def scenario():
        registry, db, agent = await setup(tmp_path)
        try:
            manager, context = await registry.complete(content="问题")
            call = await agent.created.get()
            await call.events.put({"type": "model_message.delta", "seq": 1, "message_id": "old", "delta": "不完整"})
            await call.events.put({"type": "model_request.retrying", "seq": 2, "message_id": "old", "attempt": 1})
            await next_type(context.subscription, "model_request.retrying")
            items = manager.current_turn_state.snapshot()["items"]
            assert next(item for item in items if item["id"] == "message:old")["status"] == "failed"
            await manager.cancel(context.turn_id)
            snapshot = await build_snapshot(db, await manager.attach())
            assert all(item["status"] != "retrying" for item in snapshot["state"]["turns"][0]["items"])
        finally:
            await registry.close()
            db.close()
    asyncio.run(scenario())


def test_cancelled_cold_load_still_registers_owned_manager(tmp_path, monkeypatch):
    async def scenario():
        from backend.crud import crud
        registry, db, agent = await setup(tmp_path)
        entered, release, loaded = asyncio.Event(), asyncio.Event(), asyncio.Event()
        original = registry._load
        async def delayed(session_id):
            entered.set()
            await release.wait()
            result = await original(session_id)
            loaded.set()
            return result
        monkeypatch.setattr(registry, "_load", delayed)
        try:
            crud.create_session(db.connect(), session_id="cold", status="ready", now="now")
            request = asyncio.create_task(registry.get_or_load("cold"))
            await entered.wait()
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request
            release.set()
            await loaded.wait()
            assert "cold" in registry.managers
            assert "cold" not in registry.loading
        finally:
            release.set()
            await registry.close()
            db.close()
    asyncio.run(scenario())


def test_missing_tool_result_does_not_fabricate_history(tmp_path):
    async def scenario():
        registry, db, agent = await setup(tmp_path)
        try:
            manager, context = await registry.complete(content="问题")
            call = await agent.created.get()
            await call.events.put({"type": "model_message.done", "seq": 1, "message_id": "tools", "content": "查询",
                                   "tool_calls": [{"id": "a", "name": "read", "args_json": "{}"}]})
            await next_type(context.subscription, "model_message.done")
            runtime = manager.runtimes[context.turn_id]
            with pytest.raises(ValueError, match="工具结果"):
                await manager.agent_event(context.turn_id, runtime.generation,
                                          {"type": "tool_completed", "seq": 2, "tool_call_id": "a", "tool": "read"})
            assert db.connect().execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0] == 1
        finally:
            await registry.close()
            db.close()
    asyncio.run(scenario())
