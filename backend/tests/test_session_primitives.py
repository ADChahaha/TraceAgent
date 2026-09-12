"""验证事务回滚、当前轮累积和订阅背压。"""

import asyncio
import sqlite3

import pytest

from backend.core.db import connect_database, initialize_database
from backend.crud import crud
from backend.services.turn_view import TurnView
from backend.services.subscription import Subscription, SubscriptionClosed


def test_transaction_rolls_back_all_crud_writes(tmp_path):
    db = connect_database(tmp_path / "atomic.sqlite3")
    initialize_database(db)
    with pytest.raises(sqlite3.IntegrityError):
        with crud.transaction(db):
            crud.create_session(db, session_id="s", status="ready", now="now", commit=False)
            crud.create_turn(db, session_id="missing", turn_id="t", status="queued", now="now", commit=False)
    assert crud.get_session(db, "s") is None
    db.close()


def test_turn_view_done_replaces_deltas_and_keeps_attempts_separate():
    view = TurnView("t")
    view.apply({"type": "model_message.delta", "payload": {"message_id": "a", "delta": "旧尝试"}})
    view.apply({"type": "model_message.delta", "payload": {"message_id": "b", "delta": "你好"}})
    view.apply({"type": "model_message.done", "payload": {"message_id": "b", "content": "你好世界"}})
    assert [item["text"] for item in view.snapshot()["items"]] == ["旧尝试", "你好世界"]


def test_subscription_overflow_closes_only_slow_subscriber():
    async def scenario():
        slow = Subscription(max_events=1, max_bytes=1024)
        fast = Subscription(max_events=2, max_bytes=1024)
        for subscriber in (slow, fast):
            subscriber.publish({"type": "one"})
        assert await fast.receive() == {"type": "one"}
        assert not slow.publish({"type": "two"})
        assert fast.publish({"type": "two"})
        with pytest.raises(SubscriptionClosed):
            await slow.receive()
        assert await fast.receive() == {"type": "two"}
    asyncio.run(scenario())


def test_runtime_cancel_before_first_step_cleans_up():
    async def scenario():
        from backend.services.turn_runtime import TurnRuntime
        ended = asyncio.Event()
        class Manager:
            async def worker_ended(self, turn_id, generation, error):
                ended.set()
        runtime = TurnRuntime(Manager(), "turn", [], {})
        runtime.start()
        runtime.cancel()
        runtime.cancel()
        await asyncio.gather(runtime.task, return_exceptions=True)
        await asyncio.wait_for(ended.wait(), 0.5)
    asyncio.run(scenario())


def test_cancelled_subscription_wait_does_not_consume_an_event():
    async def scenario():
        subscription = Subscription()
        receive = asyncio.create_task(subscription.receive())
        await asyncio.sleep(0)
        subscription.publish({"type": "keep"})
        asyncio.get_running_loop().call_soon(receive.cancel)
        await asyncio.gather(receive, return_exceptions=True)
        if receive.cancelled():
            assert await asyncio.wait_for(subscription.receive(), 0.5) == {"type": "keep"}
        else:
            assert receive.result() == {"type": "keep"}
    asyncio.run(scenario())


def test_services_delegate_sql_to_crud():
    import ast
    from pathlib import Path

    services = Path(__file__).resolve().parents[1] / "services"
    violations = []
    for path in services.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in {"execute", "executemany", "executescript"}):
                violations.append(f"{path.name}:{node.lineno}")
    assert not violations, violations
