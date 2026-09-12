"""对齐 models/schema.py 的 Chat CRUD 行为验证：所有读写严格贴合新表结构。"""

import sqlite3

import pytest

from backend.core.db import connect_database, initialize_database
from backend.crud import crud as chat_crud


@pytest.fixture
def db(tmp_path):
    connection = connect_database(tmp_path / "crud.sqlite3")
    initialize_database(connection)
    yield connection
    connection.close()


def create_session(db, session_id="session-1", status="processing", now="2026-01-01T00:00:00Z"):
    return chat_crud.create_session(db, session_id=session_id, status=status, now=now)


def create_turn(db, turn_id="turn-1", session_id="session-1", status="queued", now="2026-01-01T00:00:00Z"):
    return chat_crud.create_turn(db, turn_id=turn_id, session_id=session_id, status=status, now=now)


def test_create_session_writes_only_schema_columns(db):
    session = create_session(db)
    assert set(session) == {"id", "status", "active_turn_id", "created_at", "updated_at"}
    assert session["id"] == "session-1"
    assert session["status"] == "processing"
    assert session["active_turn_id"] is None
    assert chat_crud.get_session(db, "session-1") == session
    assert chat_crud.get_session(db, "missing") is None


def test_update_session_status_and_active_turn(db):
    create_session(db)
    updated = chat_crud.update_session(
        db,
        session_id="session-1",
        now="2026-01-02T00:00:00Z",
        status="running",
        active_turn_id="turn-1",
    )
    assert updated["status"] == "running"
    assert updated["active_turn_id"] == "turn-1"
    assert updated["updated_at"] == "2026-01-02T00:00:00Z"


def test_update_session_clear_active_turn(db):
    create_session(db)
    chat_crud.update_session(db, session_id="session-1", now="t1", active_turn_id="turn-1")
    cleared = chat_crud.update_session(db, session_id="session-1", now="t2", clear_active_turn=True)
    assert cleared["active_turn_id"] is None


def test_list_sessions_orders_by_updated_at_desc(db):
    create_session(db, session_id="old", now="2026-01-01T00:00:00Z")
    create_session(db, session_id="new", now="2026-01-03T00:00:00Z")
    create_session(db, session_id="mid", now="2026-01-02T00:00:00Z")
    ids = [session["id"] for session in chat_crud.list_sessions(db, limit=10)]
    assert ids == ["new", "mid", "old"]


def test_create_and_list_resource_columns(db):
    create_session(db)
    first = chat_crud.create_resource(
        db,
        resource_id="res-1",
        session_id="session-1",
        resource_type="display_html",
        location="<p id=\"p1\">text</p>",
        now="2026-01-01T00:00:00Z",
    )
    chat_crud.create_resource(
        db,
        resource_id="res-2",
        session_id="session-1",
        resource_type="markdown",
        location="# title",
        now="2026-01-02T00:00:00Z",
    )
    assert set(first) == {"id", "session_id", "type", "location", "created_at"}
    resources = chat_crud.list_resources(db, "session-1")
    assert [resource["id"] for resource in resources] == ["res-1", "res-2"]
    assert resources[1]["type"] == "markdown"
    assert resources[1]["location"] == "# title"


def test_list_resources_filters_by_type(db):
    create_session(db)
    chat_crud.create_resource(db, resource_id="res-1", session_id="session-1",
                            resource_type="html", location="<h1>x</h1>", now="t1")
    chat_crud.create_resource(db, resource_id="res-2", session_id="session-1",
                            resource_type="markdown", location="# x", now="t2")
    filtered = chat_crud.list_resources(db, "session-1", resource_type="markdown")
    assert [resource["id"] for resource in filtered] == ["res-2"]


def test_resource_unique_per_session_type_location(db):
    create_session(db)
    chat_crud.create_resource(db, resource_id="res-1", session_id="session-1",
                            resource_type="html", location="<h1>x</h1>", now="t1")
    with pytest.raises(sqlite3.IntegrityError):
        chat_crud.create_resource(db, resource_id="res-2", session_id="session-1",
                                resource_type="html", location="<h1>x</h1>", now="t2")


def test_create_and_list_message_columns(db):
    create_session(db)
    create_turn(db)
    message = chat_crud.create_message(
        db,
        message_id="msg-1",
        session_id="session-1",
        turn_id="turn-1",
        role="user",
        content="合同可以提前终止吗？",
        now="2026-01-01T00:00:00Z",
        sequence=1,
        group_id="g-user",
        group_index=0,
    )
    assert set(message) == {
        "id", "session_id", "turn_id", "sequence", "group_id", "group_index",
        "role", "content", "tool_calls_json", "tool_call_id", "name", "created_at",
    }
    assert message["role"] == "user"
    assert message["sequence"] == 1
    assert message["tool_calls_json"] == "[]"
    assert message["tool_call_id"] is None
    assert message["name"] is None
    assert [row["id"] for row in chat_crud.list_messages(db, "session-1")] == ["msg-1"]


def test_list_messages_orders_by_sequence(db):
    create_session(db)
    create_turn(db)
    chat_crud.create_message(db, message_id="later", session_id="session-1", turn_id="turn-1",
                           role="user", content="第二个问题", now="t2",
                           sequence=2, group_id="g2", group_index=0)
    chat_crud.create_message(db, message_id="earlier", session_id="session-1", turn_id="turn-1",
                           role="user", content="第一个问题", now="t1",
                           sequence=1, group_id="g1", group_index=0)
    assert [row["id"] for row in chat_crud.list_messages(db, "session-1")] == ["earlier", "later"]


def test_create_tool_message_with_tool_call_fields(db):
    create_session(db)
    create_turn(db)
    tool_calls = '[{"id":"call-a","type":"function","function":{"name":"read","arguments":"{}"}}]'
    tool = chat_crud.create_message(
        db,
        message_id="msg-tool",
        session_id="session-1",
        turn_id="turn-1",
        role="assistant",
        content="查询中",
        now="2026-01-01T00:00:00Z",
        sequence=1,
        group_id="g-group",
        group_index=0,
        tool_calls_json=tool_calls,
    )
    assert tool["tool_calls_json"] == tool_calls
    result = chat_crud.create_message(
        db,
        message_id="msg-result",
        session_id="session-1",
        turn_id="turn-1",
        role="tool",
        content='{"ok":true}',
        now="2026-01-01T00:00:01Z",
        sequence=2,
        group_id="g-group",
        group_index=1,
        tool_call_id="call-a",
        name="read",
    )
    assert result["tool_call_id"] == "call-a"
    assert result["name"] == "read"
    assert result["content"] == '{"ok":true}'


def test_create_turn_writes_only_schema_columns(db):
    create_session(db)
    turn = create_turn(db)
    assert set(turn) == {
        "id", "session_id", "status", "agent_completion_id",
        "created_at", "updated_at", "completed_at",
    }
    assert turn["status"] == "queued"
    assert turn["agent_completion_id"] is None
    assert turn["completed_at"] is None
    assert chat_crud.get_turn(db, "turn-1") == turn


def test_update_turn_status_and_completion_id(db):
    create_session(db)
    create_turn(db)
    updated = chat_crud.update_turn(
        db,
        turn_id="turn-1",
        now="2026-01-02T00:00:00Z",
        status="in_progress",
        agent_completion_id="cmp-1",
    )
    assert updated["status"] == "in_progress"
    assert updated["agent_completion_id"] == "cmp-1"
    assert updated["completed_at"] is None
    finished = chat_crud.update_turn(
        db,
        turn_id="turn-1",
        now="2026-01-03T00:00:00Z",
        status="completed",
        completed_at="2026-01-03T00:00:00Z",
    )
    assert finished["completed_at"] == "2026-01-03T00:00:00Z"


def test_update_turn_status_if_current_conditional(db):
    create_session(db)
    create_turn(db)
    updated = chat_crud.update_turn_status_if_current(
        db,
        turn_id="turn-1",
        current_statuses={"queued", "in_progress"},
        status="completed",
        now="2026-01-02T00:00:00Z",
        completed_at="2026-01-02T00:00:00Z",
    )
    assert updated is not None
    assert updated["status"] == "completed"
    stale = chat_crud.update_turn_status_if_current(
        db,
        turn_id="turn-1",
        current_statuses={"queued", "in_progress"},
        status="failed",
        now="2026-01-03T00:00:00Z",
    )
    assert stale is None
    assert chat_crud.get_turn(db, "turn-1")["status"] == "completed"


def test_get_active_turn_finds_non_terminal_turn(db):
    create_session(db)
    create_turn(db, turn_id="turn-done", status="completed")
    create_turn(db, turn_id="turn-active", status="in_progress", now="2026-01-02T00:00:00Z")
    active = chat_crud.get_active_turn(db, "session-1")
    assert active is not None
    assert active["id"] == "turn-active"


def test_create_event_assigns_sequence_and_columns(db):
    create_session(db)
    first = chat_crud.create_event(
        db,
        event_id="event-1",
        session_id="session-1",
        turn_id=None,
        event_type="session.created",
        payload={"metadata": {}},
        now="2026-01-01T00:00:00Z",
    )
    second = chat_crud.create_event(
        db,
        event_id="event-2",
        session_id="session-1",
        turn_id="turn-1",
        event_type="turn.created",
        payload={"turn_id": "turn-1"},
        now="2026-01-02T00:00:00Z",
    )
    assert set(first) == {"id", "session_id", "turn_id", "sequence",
                          "event_type", "payload_json", "created_at"}
    assert first["sequence"] == 1
    assert second["sequence"] == 2
    assert second["payload_json"] == '{"turn_id": "turn-1"}' or second["payload_json"] == '{"turn_id":"turn-1"}'


def test_list_events_after_sequence(db):
    create_session(db)
    for index in range(3):
        chat_crud.create_event(
            db,
            event_id=f"event-{index + 1}",
            session_id="session-1",
            turn_id=None,
            event_type="agent.event",
            payload={"index": index},
            now=f"2026-01-0{index + 1}T00:00:00Z",
        )
    events = chat_crud.list_events(db, "session-1", after_sequence=1)
    assert [event["sequence"] for event in events] == [2, 3]


def test_get_last_event_sequence(db):
    create_session(db)
    assert chat_crud.get_last_event_sequence(db, "session-1") == 0
    chat_crud.create_event(db, event_id="event-1", session_id="session-1", turn_id=None,
                         event_type="session.created", payload={}, now="t1")
    assert chat_crud.get_last_event_sequence(db, "session-1") == 1