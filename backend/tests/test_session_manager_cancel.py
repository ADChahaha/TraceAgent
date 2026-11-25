"""SessionManager 取消、订阅回收与启动失败边界测试。"""

from __future__ import annotations

import asyncio

import pytest

from backend.crud import crud
from backend.services.errors import ConflictError
from backend.services.session_registry import ManagerState
from backend.tests.session_fakes import new_session_complete, setup, wait_for_condition


def test_cancel_rejects_late_event_and_does_not_cancel_new_turn(tmp_path):
    async def scenario():
        registry, db, agent = await setup(tmp_path)
        try:
            manager, first = await new_session_complete(registry, "旧问题")
            call = await agent.created.get()
            old_runtime = manager.runtime
            assert (await manager.cancel(first.turn_id))["status"] == "cancelled"
            assert call.cancelled
            second = await manager.create_completion(content="新问题", run_options={})
            new_call = await agent.created.get()
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
            with crud.transaction(db.connect()):
                crud.create_session(db.connect(), session_id="cold", status="ready", now="now")

            async def submit_cold():
                manager = await registry.get_or_create("cold")
                return await manager.create_completion(content="问题", run_options={})

            request = asyncio.create_task(submit_cold())
            await entered.wait()
            assert registry.entries["cold"].state is ManagerState.CREATING
            with pytest.raises(ConflictError):
                await registry.get("cold")
            with pytest.raises(ConflictError):
                await registry.get_or_create("cold")
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request
            assert "cold" not in registry.entries
            assert db.connect().execute("SELECT COUNT(*) FROM chat_turns").fetchone()[0] == 0
            release.set()
            manager = await registry.get_or_create("cold")
            context = await manager.create_completion(content="重试", run_options={})
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
            with crud.transaction(db.connect()):
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
            with crud.transaction(db.connect()):
                crud.create_session(db.connect(), session_id="cold", status="ready", now="now")
            manager = await registry.get_or_create("cold")
            entered, release = asyncio.Event(), asyncio.Event()
            original_publish = manager._runtime_publish

            async def gated_publish(event):
                entered.set()
                await release.wait()
                return await original_publish(event)

            monkeypatch.setattr(manager, "_runtime_publish", gated_publish)
            request = asyncio.create_task(manager.create_completion(content="问题", run_options={}))
            try:
                await entered.wait()
                request.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await request
            finally:
                release.set()
            await wait_for_condition(lambda: not manager.subscribers and manager.runtime is not None)
        finally:
            await registry.close()
            db.close()
    asyncio.run(scenario())


def test_failed_begin_returns_error_without_runtime_or_subscription(tmp_path, monkeypatch):
    async def scenario():
        registry, db, agent = await setup(tmp_path)
        try:
            with crud.transaction(db.connect()):
                crud.create_session(db.connect(), session_id="cold", status="ready", now="now")
            manager = await registry.get_or_create("cold")

            class BrokenDatabase:
                def connect(self):
                    raise RuntimeError("写库失败")

            monkeypatch.setattr(manager, "database", BrokenDatabase())
            with pytest.raises(RuntimeError, match="写库失败"):
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
            with crud.transaction(db.connect()):
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
