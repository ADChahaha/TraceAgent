"""真实 SQLite 与可控事件流验证会话恢复、取消和事务边界。"""

import asyncio
import copy

import pytest

from backend.core.config import BackendSettings
from backend.core.db import ThreadLocalDatabase, initialize_database
from backend.crud import crud
from backend.services.session_registry import ManagerState, SessionRegistry
from backend.services.session_history import build_snapshot
from backend.services.errors import ConflictError, NotFoundError


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
        # 记录会话级资源调用：(session_id, files, remove_raw)；轮次执行不得触达。
        self.prepared = []

    async def prepare_resources(self, *, session_id, files, remove_raw=None):
        self.prepared.append((session_id, files, list(remove_raw or [])))
        bucket = f"res_{session_id}"
        refs = [{"type": "documents", "location": f"s3://{bucket}/documents.zip"},
                {"type": "index", "location": f"s3://{bucket}/index"}]
        removed = {ref["location"] for ref in (remove_raw or [])}
        for file in files:
            location = f"s3://{bucket}/raw/{file['filename']}"
            if location not in removed:
                refs.append({"type": "raw", "location": location})
        return refs

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




async def new_session_complete(registry, content, **kwargs):
    """新契约：先独立建会话，再在该会话上发起轮次。"""
    session_id = await registry.create_session()
    return await registry.complete(content=content, session_id=session_id, **kwargs)


async def next_type(subscription, expected):
    while True:
        event = await asyncio.wait_for(subscription.receive(), 2)
        if event["type"] == expected:
            return event


async def wait_for_condition(predicate, timeout=2):
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("等待条件超时")
        await asyncio.sleep(0.01)


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
            manager, first = await new_session_complete(registry, "第一问")
            call = await asyncio.wait_for(agent.created.get(), 2)
            await manager.detach(first.subscription.id)
            assert not call.cancelled
            await finish(call, manager, first.turn_id)
            assert manager.runtime is None
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


def test_snapshot_renders_history_from_messages_without_events(tmp_path):
    async def scenario():
        registry, db, agent = await setup(tmp_path)
        try:
            conn = db.connect()
            crud.create_session(conn, session_id="hist", status="ready", now="t0")
            crud.create_turn(conn, session_id="hist", turn_id="t1", status="completed", now="t1")
            crud.create_message(conn, message_id="u1", session_id="hist", turn_id="t1", role="user",
                                content="第一问", now="t1", sequence=1, group_id="g1", group_index=0)
            crud.create_message(conn, message_id="a1", session_id="hist", turn_id="t1", role="assistant",
                                content="查询", now="t1", sequence=2, group_id="g2", group_index=0,
                                tool_calls_json='[{"id":"call-a","type":"function","function":{"name":"read","arguments":"{}"}},'
                                                '{"id":"call-b","type":"function","function":{"name":"read","arguments":"{}"}}]')
            crud.create_message(conn, message_id="r1", session_id="hist", turn_id="t1", role="tool",
                                content='{"value":1}', now="t1", sequence=3, group_id="g2", group_index=1,
                                tool_call_id="call-a", name="read")
            crud.create_message(conn, message_id="r2", session_id="hist", turn_id="t1", role="tool",
                                content='{"error":"missing"}', now="t1", sequence=4, group_id="g2", group_index=2,
                                tool_call_id="call-b", name="read")
            crud.create_message(conn, message_id="a2", session_id="hist", turn_id="t1", role="assistant",
                                content="回答", now="t1", sequence=5, group_id="g3", group_index=0)
            crud.create_turn(conn, session_id="hist", turn_id="t2", status="failed", now="t2", error="backend_restarted")
            crud.create_message(conn, message_id="u2", session_id="hist", turn_id="t2", role="user",
                                content="第二问", now="t2", sequence=6, group_id="g4", group_index=0)
            manager = await registry.get_or_create("hist")
            snapshot = await build_snapshot(db, await manager.attach())
            turns = snapshot["state"]["turns"]
            assert turns[0] == {
                "id": "t1", "status": "completed", "error": None,
                "items": [
                    {"id": "u1", "kind": "user", "text": "第一问", "status": "completed"},
                    {"id": "message:a1", "kind": "assistant", "text": "查询", "status": "completed",
                     "tool_calls": [{"id": "call-a", "name": "read", "args_json": "{}"},
                                    {"id": "call-b", "name": "read", "args_json": "{}"}]},
                    {"id": "tool:call-a", "kind": "tool", "name": "read", "status": "completed",
                     "detail": {"tool_call_id": "call-a", "tool": "read", "result_json": '{"value":1}'}},
                    {"id": "tool:call-b", "kind": "tool", "name": "read", "status": "failed",
                     "detail": {"tool_call_id": "call-b", "tool": "read", "error": "missing"}},
                    {"id": "message:a2", "kind": "assistant", "text": "回答", "status": "completed"},
                ],
            }
            assert turns[1] == {
                "id": "t2", "status": "failed", "error": "backend_restarted",
                "items": [{"id": "u2", "kind": "user", "text": "第二问", "status": "completed"}],
            }
        finally:
            await registry.close()
            db.close()
    asyncio.run(scenario())


def test_attach_snapshot_survives_completion_and_next_turn(tmp_path):
    async def scenario():
        registry, db, agent = await setup(tmp_path)
        try:
            manager, first = await new_session_complete(registry, "问题")
            call = await agent.created.get()
            context = await manager.attach()
            await finish(call, manager, first.turn_id)
            _, second = await registry.complete(session_id=manager.session_id, content="新问题")
            snapshot = await build_snapshot(db, context)
            assert len(snapshot["state"]["turns"]) == 1
            assert snapshot["state"]["turns"][0]["status"] != "completed"
            assert snapshot["state"]["active_turn_id"] == first.turn_id
            await next_type(context.subscription, "turn.completed")
            event = await next_type(context.subscription, "turn.created")
            assert event["turn_id"] == second.turn_id
        finally:
            await registry.close()
            db.close()
    asyncio.run(scenario())


def test_created_turn_snapshot_carries_user_message(tmp_path):
    async def scenario():
        registry, db, agent = await setup(tmp_path)
        try:
            manager, context = await new_session_complete(registry, "问题")
            snapshot = await build_snapshot(db, context)
            current = snapshot["state"]["turns"][-1]
            assert current["id"] == context.turn_id
            assert current["status"] == "in_progress"
            assert [item["kind"] for item in current["items"]] == ["user"]
            assert current["items"][0]["text"] == "问题"
        finally:
            await registry.close()
            db.close()
    asyncio.run(scenario())


def test_cancel_rejects_late_event_and_does_not_cancel_new_turn(tmp_path):
    async def scenario():
        registry, db, agent = await setup(tmp_path)
        try:
            manager, first = await new_session_complete(registry, "旧问题")
            call = await agent.created.get()
            old_runtime = manager.runtime
            assert (await manager.cancel(first.turn_id))["status"] == "cancelled"
            assert call.cancelled
            _, second = await registry.complete(session_id=manager.session_id, content="新问题")
            new_call = await agent.created.get()
            # 取消后旧 runtime 的事件被 runtime 自身丢弃：直接对旧 runtime 投递验证。
            await old_runtime._on_event({"type": "model_message.done", "message_id": "late", "content": "迟到"})
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
            manager, first = await new_session_complete(registry, "问题")
            managers = await asyncio.gather(*(registry.get_or_create(manager.session_id) for _ in range(8)))
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
            first, _ = await new_session_complete(registry, "问题")
            second, _ = await new_session_complete(registry, "问题")
            assert first.session_id != second.session_id
            assert db.connect().execute("SELECT COUNT(*) FROM chat_turns").fetchone()[0] == 2
        finally:
            await registry.close()
            db.close()
    asyncio.run(scenario())



def test_cancelled_creation_aborts_ownership_and_retry(tmp_path, monkeypatch):
    async def scenario():
        registry, db, agent = await setup(tmp_path)
        entered, release = asyncio.Event(), asyncio.Event()
        original = registry._load_manager

        async def delayed(session_id):
            entered.set()
            await release.wait()
            return await original(session_id)

        monkeypatch.setattr(registry, "_load_manager", delayed)
        try:
            crud.create_session(db.connect(), session_id="cold", status="ready", now="now")
            request = asyncio.create_task(registry.complete(session_id="cold", content="问题"))
            await entered.wait()
            assert registry.entries["cold"].state is ManagerState.CREATING
            with pytest.raises(ConflictError):
                await registry.get("cold")
            with pytest.raises(ConflictError):
                await registry.complete(session_id="cold", content="另一问")
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request
            assert "cold" not in registry.entries
            assert db.connect().execute("SELECT COUNT(*) FROM chat_turns").fetchone()[0] == 0
            release.set()
            manager, context = await registry.complete(session_id="cold", content="重试")
            assert manager.active_turn_id == context.turn_id
        finally:
            release.set()
            await registry.close()
            db.close()
    asyncio.run(scenario())



def test_cancelled_queued_create_recycles_subscription(tmp_path, monkeypatch):
    async def scenario():
        registry, db, agent = await setup(tmp_path)
        try:
            crud.create_session(db.connect(), session_id="cold", status="ready", now="now")
            manager = await registry.get_or_create("cold")
            entered, release = asyncio.Event(), asyncio.Event()
            original_detach = manager._handle_detach

            async def gated_detach(subscription_id):
                entered.set()
                await release.wait()
                return await original_detach(subscription_id)

            monkeypatch.setattr(manager, "_handle_detach", gated_detach)

            blocker = asyncio.create_task(manager.detach("nonexistent"))
            await entered.wait()
            request = asyncio.create_task(manager.create_completion(content="问题", run_options={}))
            await asyncio.sleep(0)
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request
            release.set()
            await blocker
            # 命令仍执行并创建轮次；无人接收的订阅由 _run 回收。
            await wait_for_condition(lambda: not manager.subscribers and manager.runtime is not None)
        finally:
            release.set()
            await registry.close()
            db.close()
    asyncio.run(scenario())


def test_cancelled_create_during_handler_recycles_subscription(tmp_path, monkeypatch):
    async def scenario():
        registry, db, agent = await setup(tmp_path)
        try:
            crud.create_session(db.connect(), session_id="cold", status="ready", now="now")
            manager = await registry.get_or_create("cold")
            entered, release = asyncio.Event(), asyncio.Event()
            original_commit = manager._runtime_commit

            async def gated_commit(operation, events):
                entered.set()
                await release.wait()
                return await original_commit(operation, events)

            monkeypatch.setattr(manager, "_runtime_commit", gated_commit)

            request = asyncio.create_task(manager.create_completion(content="问题", run_options={}))
            try:
                await entered.wait()
                request.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await request
            finally:
                release.set()
            # 命令仍执行并创建轮次；无人接收的订阅由 _run 回收。
            await wait_for_condition(lambda: not manager.subscribers and manager.runtime is not None)
        finally:
            await registry.close()
            db.close()
    asyncio.run(scenario())


def test_failed_begin_returns_error_without_runtime_or_subscription(tmp_path, monkeypatch):
    async def scenario():
        registry, db, agent = await setup(tmp_path)
        try:
            crud.create_session(db.connect(), session_id="cold", status="ready", now="now")
            manager = await registry.get_or_create("cold")

            async def failing_commit(operation, events):
                raise RuntimeError("写入失败")

            monkeypatch.setattr(manager, "_runtime_commit", failing_commit)
            with pytest.raises(RuntimeError, match="写入失败"):
                await manager.create_completion(content="问题", run_options={})
            assert manager.subscribers == {}
            assert manager.active_turn_id is None
            assert db.connect().execute("SELECT COUNT(*) FROM chat_turns").fetchone()[0] == 0
            assert db.connect().execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0] == 0
        finally:
            await registry.close()
            db.close()
    asyncio.run(scenario())


def test_cancel_rejects_events_after_signal(tmp_path):
    async def scenario():
        registry, db, agent = await setup(tmp_path)
        try:
            manager, context = await new_session_complete(registry, "问题")
            call = await agent.created.get()
            runtime = manager.runtime
            assert (await manager.cancel(context.turn_id))["status"] == "cancelled"
            assert call.cancelled
            # 取消信号后 runtime 丢弃后续事件，不写库。
            accepted = await runtime._on_event(
                {"type": "model_message.done", "seq": 1, "message_id": "late", "content": "迟到"})
            assert accepted is False
            rows = db.connect().execute("SELECT role, content FROM chat_messages ORDER BY sequence").fetchall()
            assert [tuple(row) for row in rows] == [("user", "问题")]
        finally:
            await registry.close()
            db.close()
    asyncio.run(scenario())


def test_cancelled_caller_after_result_recycles_subscription(tmp_path, monkeypatch):
    async def scenario():
        registry, db, agent = await setup(tmp_path)
        try:
            crud.create_session(db.connect(), session_id="cold", status="ready", now="now")
            manager = await registry.get_or_create("cold")
            loop = asyncio.get_running_loop()
            holder = {}
            attached = []
            original_attach = manager._handle_attach

            async def hijack():
                context = await original_attach()
                attached.append(context)
                loop.call_soon(holder["task"].cancel)
                return context

            monkeypatch.setattr(manager, "_handle_attach", hijack)
            task = asyncio.create_task(manager.attach())
            holder["task"] = task
            with pytest.raises(asyncio.CancelledError):
                await task
            assert attached[0].subscription.closed.is_set()
            assert manager.subscribers == {}
        finally:
            await registry.close()
            db.close()
    asyncio.run(scenario())


def test_tool_group_is_atomic_and_next_history_uses_original_ids(tmp_path):
    async def scenario():
        registry, db, agent = await setup(tmp_path)
        try:
            manager, context = await new_session_complete(registry, "读两个位置")
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


def test_tool_write_failure_rolls_back_group(tmp_path):
    async def scenario():
        from backend.services.subscription import SubscriptionClosed
        registry, db, agent = await setup(tmp_path)
        try:
            manager, context = await new_session_complete(registry, "问题")
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
            assert manager.broken
            # manager.fail 已取消 runtime；等它收尾后再关库，避免跨线程关闭在途连接。
            if manager.runtime is not None:
                await manager.runtime.wait_closed()
        finally:
            await registry.close()
            db.close()
    asyncio.run(scenario())


def test_idle_unload_and_cold_resume_do_not_keep_history_in_manager(tmp_path):
    async def scenario():
        registry, db, agent = await setup(tmp_path)
        try:
            manager, first = await new_session_complete(registry, "问题")
            call = await agent.created.get()
            await manager.detach(first.subscription.id)
            manager.last_activity = 0
            await registry.evict_idle()
            assert registry.entries[manager.session_id].manager is manager
            await finish(call, manager, first.turn_id)
            if manager.runtime is not None:
                await manager.runtime.wait_closed()
            manager.last_activity = 0
            await registry.evict_idle()
            assert manager.session_id not in registry.entries
            loaded = await registry.get_or_create(manager.session_id)
            assert loaded is not manager and loaded.runtime is None
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
            manager = await registry.get_or_create("orphan")
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
            manager, context = await new_session_complete(registry, "问题")
            call = await agent.created.get()
            await call.events.put({"type": "model_message.delta", "seq": 1, "message_id": "old", "delta": "不完整"})
            await call.events.put({"type": "model_request.retrying", "seq": 2, "message_id": "old", "attempt": 1})
            await next_type(context.subscription, "model_request.retrying")
            items = manager.runtime.snapshot()["items"]
            assert next(item for item in items if item["id"] == "message:old")["status"] == "failed"
            await manager.cancel(context.turn_id)
            snapshot = await build_snapshot(db, await manager.attach())
            assert all(item["status"] != "retrying" for item in snapshot["state"]["turns"][0]["items"])
        finally:
            await registry.close()
            db.close()
    asyncio.run(scenario())


def test_closing_entry_rejects_get_until_removed(tmp_path, monkeypatch):
    async def scenario():
        registry, db, agent = await setup(tmp_path)
        try:
            manager, context = await new_session_complete(registry, "问题")
            call = await agent.created.get()
            await manager.detach(context.subscription.id)
            await finish(call, manager, context.turn_id)
            if manager.runtime is not None:
                await manager.runtime.wait_closed()
            manager.last_activity = 0
            entered, release = asyncio.Event(), asyncio.Event()
            original_close = manager.close

            async def blocked_close():
                entered.set()
                await release.wait()
                await original_close()

            monkeypatch.setattr(manager, "close", blocked_close)
            evict = asyncio.create_task(registry.evict_idle())
            await entered.wait()
            assert registry.entries[manager.session_id].state is ManagerState.CLOSING
            with pytest.raises(ConflictError):
                await registry.get(manager.session_id)
            with pytest.raises(ConflictError):
                await registry.complete(session_id=manager.session_id, content="新问题")
            release.set()
            await evict
            assert manager.session_id not in registry.entries
            restored = await registry.get_or_create(manager.session_id)
            assert restored is not manager
        finally:
            release.set()
            await registry.close()
            db.close()
    asyncio.run(scenario())


def test_get_unknown_session_raises_not_found(tmp_path):
    async def scenario():
        registry, db, agent = await setup(tmp_path)
        try:
            with pytest.raises(NotFoundError):
                await registry.get("missing")
        finally:
            await registry.close()
            db.close()
    asyncio.run(scenario())


def test_missing_tool_result_does_not_fabricate_history(tmp_path):
    async def scenario():
        registry, db, agent = await setup(tmp_path)
        try:
            manager, context = await new_session_complete(registry, "问题")
            call = await agent.created.get()
            await call.events.put({"type": "model_message.done", "seq": 1, "message_id": "tools", "content": "查询",
                                   "tool_calls": [{"id": "a", "name": "read", "args_json": "{}"}]})
            await next_type(context.subscription, "model_message.done")
            runtime = manager.runtime
            with pytest.raises(ValueError, match="工具结果"):
                await runtime._on_event({"type": "tool_completed", "seq": 2, "tool_call_id": "a", "tool": "read"})
            assert db.connect().execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0] == 1
        finally:
            await registry.close()
            db.close()
    asyncio.run(scenario())


def test_registry_can_load_after_cleanup(tmp_path):
    async def scenario():
        registry, db, agent = await setup(tmp_path)
        try:
            manager, context = await new_session_complete(registry, "问题")
            session_id = manager.session_id
            await registry.close()
            restored = await registry.get_or_create(session_id)
            assert restored is not manager
            assert restored.session_id == session_id
            assert restored.active_turn_id is None
        finally:
            await registry.close()
            db.close()
    asyncio.run(scenario())
