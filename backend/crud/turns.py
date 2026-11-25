"""对话轮次表（chat_turns）与消息表（chat_messages）读写函数。"""

from __future__ import annotations

import sqlite3
from typing import Any

from backend.core.db import row_to_dict


def create_message(
    connection: sqlite3.Connection,
    *,
    message_id: str,
    session_id: str,
    turn_id: str | None,
    role: str,
    content: str,
    now: str,
    sequence: int,
    group_id: str,
    group_index: int,
    tool_calls_json: str = "[]",
    tool_call_id: str | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    connection.execute(
        """
        INSERT INTO chat_messages (
            id, session_id, turn_id, sequence, group_id, group_index, role,
            content, tool_calls_json, tool_call_id, name, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            message_id,
            session_id,
            turn_id,
            sequence,
            group_id,
            group_index,
            role,
            content,
            tool_calls_json,
            tool_call_id,
            name,
            now,
        ),
    )
    row = connection.execute("SELECT * FROM chat_messages WHERE id = ?", (message_id,)).fetchone()
    message = row_to_dict(row)
    assert message is not None
    return message


def list_messages(connection: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    """按轮创建顺序、轮内 sequence 拼接返回会话全部消息，供模型上下文使用。"""
    rows = connection.execute(
        """
        SELECT m.* FROM chat_messages m
        JOIN chat_turns t ON t.id = m.turn_id
        WHERE m.session_id = ?
        ORDER BY t.created_at, t.rowid, m.sequence ASC, m.rowid ASC
        """,
        (session_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_next_message_sequence(connection: sqlite3.Connection, turn_id: str) -> int:
    """读取轮内下一消息序号；调用方须在同一写事务中分配并插入消息。"""
    return int(
        connection.execute(
            "SELECT COALESCE(MAX(sequence),0)+1 FROM chat_messages WHERE turn_id=?",
            (turn_id,),
        ).fetchone()[0]
    )


def create_turn(
    connection: sqlite3.Connection,
    *,
    turn_id: str,
    session_id: str,
    status: str,
    now: str,
    error: str | None = None,
) -> dict[str, Any]:
    connection.execute(
        """
        INSERT INTO chat_turns (
            id, session_id, status, error, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (turn_id, session_id, status, error, now, now),
    )
    turn = get_turn(connection, turn_id)
    assert turn is not None
    return turn


def get_turn(connection: sqlite3.Connection, turn_id: str) -> dict[str, Any] | None:
    row = connection.execute("SELECT * FROM chat_turns WHERE id = ?", (turn_id,)).fetchone()
    return row_to_dict(row)


def get_active_turn(connection: sqlite3.Connection, session_id: str) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT *
        FROM chat_turns
        WHERE session_id = ? AND status IN ('queued', 'in_progress', 'cancelling')
        ORDER BY created_at DESC, rowid DESC
        LIMIT 1
        """,
        (session_id,),
    ).fetchone()
    return row_to_dict(row)


def update_turn(
    connection: sqlite3.Connection,
    *,
    turn_id: str,
    now: str,
    status: str | None = None,
    agent_completion_id: str | None = None,
    error: str | None = None,
    completed_at: str | None = None,
) -> dict[str, Any]:
    updates: dict[str, Any] = {"updated_at": now}
    if status is not None:
        updates["status"] = status
    if agent_completion_id is not None:
        updates["agent_completion_id"] = agent_completion_id
    if error is not None:
        updates["error"] = error
    if completed_at is not None:
        updates["completed_at"] = completed_at
    assignments = ", ".join(f"{name} = ?" for name in updates)
    connection.execute(f"UPDATE chat_turns SET {assignments} WHERE id = ?", [*updates.values(), turn_id])
    turn = get_turn(connection, turn_id)
    assert turn is not None
    return turn


def update_turn_status_if_current(
    connection: sqlite3.Connection,
    *,
    turn_id: str,
    current_statuses: set[str],
    status: str,
    now: str,
    error: str | None = None,
    completed_at: str | None = None,
) -> dict[str, Any] | None:
    updates: dict[str, Any] = {"status": status, "updated_at": now}
    if error is not None:
        updates["error"] = error
    if completed_at is not None:
        updates["completed_at"] = completed_at
    placeholders = ", ".join("?" for _ in current_statuses)
    assignments = ", ".join(f"{name} = ?" for name in updates)
    cursor = connection.execute(
        f"""
        UPDATE chat_turns
        SET {assignments}
        WHERE id = ? AND status IN ({placeholders})
        """,
        [*updates.values(), turn_id, *sorted(current_statuses)],
    )
    if cursor.rowcount == 0:
        return None
    return get_turn(connection, turn_id)


def list_turns(connection: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    """按创建顺序返回会话全部轮次，供恢复快照渲染历史。"""
    rows = connection.execute(
        "SELECT * FROM chat_turns WHERE session_id = ? ORDER BY created_at, rowid",
        (session_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def list_unfinished_turns(connection: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    """按会话查询尚未终结的轮次，供启动恢复收口。"""
    rows = connection.execute(
        "SELECT id FROM chat_turns WHERE session_id=? "
        "AND status IN ('queued','in_progress','cancelling')",
        (session_id,),
    ).fetchall()
    return [dict(row) for row in rows]
