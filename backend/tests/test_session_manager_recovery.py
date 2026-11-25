"""SessionManager 工具事务原子性、关闭排干、空闲卸载与启动故障恢复测试。"""

from __future__ import annotations

import asyncio
import sqlite3
import threading

import pytest

from backend.crud import crud
from backend.services.errors import ConflictError
from backend.services.session_history import build_snapshot
from backend.services.session_registry import ManagerState, SessionRegistry
from backend.services.subscription import SubscriptionClosed
from backend.tests.session_fakes import (
    expire_idle,
    finish,
    new_session_complete,
    next_type,
    setup,
    wait_for_condition,
)


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
            assert manager.runtime is None
        finally:
            await registry.close()
            db.close()
    asyncio.run(scenario())


def test_close_waits_for_detached_runtime_after_fail_before_db_close(tmp_path, monkeypatch):
    async def scenario():
        registry, db, agent = await setup(tmp_path)
        entered, release = threading.Event(), threading.Event()
        real_update = crud.update_turn_status_if_current

        def slow_update(*args, **kwargs):
            entered.set()
            assert release.wait(2), "close() 阻塞时未能释放工作线程"
            return real_update(*args, **kwargs)

        try:
            manager, context = await new_session_complete(registry, "问题")
            call = await agent.created.get()
            runtime = manager.runtime
            await call.events.put({"type": "model_message.done", "seq": 1, "message_id": "tools", "content": "查询",
                                   "tool_calls": [{"id": "a", "name": "read", "args_json": "{}"}]})
            await next_type(context.subscription, "model_message.done")
            db.connect().execute("CREATE TRIGGER reject_tool BEFORE INSERT ON chat_messages WHEN NEW.role='tool' BEGIN SELECT RAISE(ABORT, 'injected'); END")
            db.connect().commit()
            monkeypatch.setattr(crud, "update_turn_status_if_current", slow_update)

            await call.events.put({"type": "tool_completed", "seq": 2, "tool_call_id": "a", "tool": "read", "result_json": "{}"})
            with pytest.raises(SubscriptionClosed):
                await next_type(context.subscription, "tool_completed")
            assert manager.broken and manager.runtime is None

            await asyncio.to_thread(entered.wait, 2)
            assert entered.is_set()
            closing = asyncio.create_task(registry.close())
            await asyncio.sleep(0.05)
            assert not closing.done(), "后台写库线程未结束前 close() 不应提前返回"
            release.set()
            await asyncio.wait_for(closing, 2)
            assert runtime.done.is_set()
            assert manager.closed
        finally:
            release.set()
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
            expire_idle(manager, registry)
            await registry.evict_idle()
            assert registry.entries[manager.session_id].manager is manager
            await finish(call, manager, first.turn_id)
            if manager.runtime is not None:
                await manager.runtime.wait_closed()
            expire_idle(manager, registry)
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
        registry, db, agent = await setup(tmp_path)
        await registry.close()
        with crud.transaction(db.connect()):
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
            expire_idle(manager, registry)
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
                await registry.get_or_create(manager.session_id)
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


def test_finish_write_failure_resolves_cancel_reclaims_and_recovers(tmp_path, monkeypatch):
    async def scenario():
        registry, db, agent = await setup(tmp_path)
        try:
            manager, context = await new_session_complete(registry, "问题")
            await agent.created.get()
            attempts = {"n": 0}
            real_update = crud.update_turn_status_if_current

            def flaky_update(*args, **kwargs):
                attempts["n"] += 1
                if attempts["n"] == 1:
                    raise sqlite3.OperationalError("injected finish failure")
                return real_update(*args, **kwargs)

            monkeypatch.setattr(crud, "update_turn_status_if_current", flaky_update)
            cancelled = asyncio.create_task(manager.cancel(context.turn_id))
            assert await asyncio.wait_for(cancelled, 2) == {"status": "failed"}
            assert manager.broken and manager.runtime is None and manager.active_turn_id is None
            assert not manager.subscribers

            def turn_status():
                return db.connect().execute("SELECT status FROM chat_turns WHERE id=?", (context.turn_id,)).fetchone()[0]

            await wait_for_condition(lambda: turn_status() == "failed")
            assert db.connect().execute("SELECT active_turn_id FROM chat_sessions WHERE id=?", (manager.session_id,)).fetchone()[0] is None
            await asyncio.wait_for(manager.close(), 2)
            expire_idle(manager, registry)
            await registry.evict_idle()
            assert manager.session_id not in registry.entries
            reloaded = await registry.get_or_create(manager.session_id)
            retried = await reloaded.create_completion(content="重试", run_options={})
            assert reloaded.active_turn_id == retried.turn_id
        finally:
            try:
                await asyncio.wait_for(registry.close(), 3)
            except asyncio.TimeoutError:
                pass
            db.close()
    asyncio.run(scenario())
