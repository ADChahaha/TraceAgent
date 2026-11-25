"""真实 SQLite 与可控事件流验证会话创建、历史快照恢复与并发边界。"""

from __future__ import annotations

import asyncio

import pytest

from backend.crud import crud
from backend.services.errors import ConflictError, NotFoundError, ValidationError
from backend.services.session_history import build_snapshot
from backend.tests.session_fakes import (
    FakeAgent,
    FakeCall,
    FakeStore,
    expire_idle,
    finish,
    new_session_complete,
    next_type,
    setup,
    wait_for_condition,
)

__all__ = [
    "FakeAgent",
    "FakeCall",
    "FakeStore",
    "expire_idle",
    "finish",
    "new_session_complete",
    "next_type",
    "setup",
    "wait_for_condition",
]


def test_manager_create_validates_content_and_run_options(tmp_path):
    async def scenario():
        registry, db, agent = await setup(tmp_path)
        try:
            session_id = await registry.create_session()
            manager = await registry.get_or_create(session_id)
            with pytest.raises(ValidationError):
                await manager.create_completion(content="   ", run_options={})
            with pytest.raises(ValidationError):
                await manager.create_completion(content="问题", run_options={"unknown": 1})
            with pytest.raises(ValidationError):
                await manager.create_completion(content="问题", run_options={"tool_execution_timeout": 0})
        finally:
            await registry.close()
            db.close()
    asyncio.run(scenario())


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
            second = await manager.create_completion(content="第二问", run_options={})
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
            with crud.transaction(conn):
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
            second = await manager.create_completion(content="新问题", run_options={})
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


def test_concurrent_create_has_one_active_turn_and_one_manager(tmp_path):
    async def scenario():
        registry, db, agent = await setup(tmp_path)
        try:
            manager, first = await new_session_complete(registry, "问题")
            managers = await asyncio.gather(*(registry.get_or_create(manager.session_id) for _ in range(8)))
            assert all(item is manager for item in managers)
            with pytest.raises(ConflictError):
                await manager.create_completion(content="并发问题", run_options={})
            assert db.connect().execute("SELECT COUNT(*) FROM chat_turns").fetchone()[0] == 1
        finally:
            await registry.close()
            db.close()
    asyncio.run(scenario())


def test_completion_has_no_request_deduplication(tmp_path):
    from backend.routes.chat import CompletionInput
    from pydantic import ValidationError as PydanticValidationError
    with pytest.raises(PydanticValidationError):
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


def test_completion_snapshot_keeps_previous_turns(tmp_path):
    async def scenario():
        registry, db, agent = await setup(tmp_path)
        try:
            manager, first = await new_session_complete(registry, "第一问")
            call = await agent.created.get()
            await finish(call, manager, first.turn_id)
            second = await manager.create_completion(content="第二问")
            snapshot = await build_snapshot(db, second)
            assert [turn["id"] for turn in snapshot["state"]["turns"]] == [first.turn_id, second.turn_id]
            assert snapshot["state"]["turns"][0]["items"][0]["text"] == "第一问"
        finally:
            await registry.close()
            db.close()
    asyncio.run(scenario())
