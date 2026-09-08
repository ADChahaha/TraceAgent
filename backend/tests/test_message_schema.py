"""真实 SQLite 初始化 → 验证稳定消息表约束及整组事务回滚。"""

import sqlite3

import pytest

from backend.core.db import connect_database, initialize_database


@pytest.fixture
def db(tmp_path):
    connection = connect_database(tmp_path / "messages.sqlite3")
    initialize_database(connection)
    for task_id in ("a", "b"):
        connection.execute(
            "INSERT INTO qa_tasks(id, status, created_at, updated_at) VALUES (?, 'ready', 'now', 'now')",
            (task_id,),
        )
        connection.execute(
            "INSERT INTO qa_turns(id, task_id, status, created_at, updated_at) VALUES (?, ?, 'in_progress', 'now', 'now')",
            (f"turn-{task_id}", task_id),
        )
    connection.commit()
    yield connection
    connection.close()


def insert_message(db, **overrides):
    values = dict(id="m1", task_id="a", turn_id="turn-a", sequence=1,
                  group_id="g1", group_index=0, role="assistant", content="正文",
                  tool_calls_json="[]", tool_call_id=None, name=None, created_at="now")
    values.update(overrides)
    db.execute(
        f"INSERT INTO qa_messages ({', '.join(values)}) VALUES ({', '.join('?' for _ in values)})",
        tuple(values.values()),
    )


def test_message_table_survives_reinitialization_and_orders_history(db):
    insert_message(db, id="second", sequence=2, group_id="g2")
    insert_message(db, id="first")
    db.commit()
    initialize_database(db)
    assert [row["id"] for row in db.execute("SELECT * FROM qa_messages ORDER BY sequence")] == ["first", "second"]
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize("changes", [
    {"role": "unknown"}, {"sequence": 0}, {"group_index": -1},
    {"role": "tool"}, {"tool_call_id": "call-a"},
    {"tool_calls_json": "not json"}, {"tool_calls_json": "{}"},
    {"role": "user", "tool_calls_json": '[{"id":"call-a"}]'},
    {"turn_id": None}, {"task_id": "missing"}, {"turn_id": "turn-b"},
])
def test_message_table_rejects_invalid_rows(db, changes):
    with pytest.raises(sqlite3.IntegrityError):
        insert_message(db, **changes)


@pytest.mark.parametrize("changes", [
    {"sequence": 1, "group_id": "g2"},
    {"sequence": 2, "group_id": "g1", "group_index": 0},
])
def test_message_table_rejects_duplicate_position(db, changes):
    insert_message(db)
    with pytest.raises(sqlite3.IntegrityError):
        insert_message(db, id="m2", **changes)


def test_message_table_tool_ids_are_unique_within_group(db):
    insert_message(db, role="tool", tool_call_id="call-a", name="read")
    with pytest.raises(sqlite3.IntegrityError):
        insert_message(db, id="m2", sequence=2, group_index=1,
                       role="tool", tool_call_id="call-a", name="read")
    insert_message(db, id="m3", sequence=3, group_id="g2",
                   role="tool", tool_call_id="call-a", name="read")


def test_message_group_transaction_rolls_back_on_write_failure(db):
    with pytest.raises(sqlite3.IntegrityError):
        with db:
            insert_message(db, tool_calls_json='[{"id":"call-a","type":"function","function":{"name":"read","arguments":"{}"}}]')
            insert_message(db, id="result", sequence=2, group_index=1,
                           role="tool", tool_call_id=None, name="read")
    assert db.execute("SELECT COUNT(*) FROM qa_messages").fetchone()[0] == 0


def test_system_message_can_exist_without_turn(db):
    insert_message(db, role="system", turn_id=None)
    assert db.execute("SELECT turn_id FROM qa_messages").fetchone()[0] is None
