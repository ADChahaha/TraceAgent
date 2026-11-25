"""会话表读写与显式写事务原语。"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Any

from backend.core.db import row_to_dict


@contextmanager
def transaction(connection: sqlite3.Connection):
    """同一线程内开启写事务；失败全部回滚，成功统一提交。提交权只在边界持有者
    手里：本模块的写函数只执行语句，永不自行提交。"""
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def create_session(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    status: str,
    now: str,
) -> dict[str, Any]:
    connection.execute(
        """
        INSERT INTO chat_sessions (
            id, status, created_at, updated_at
        )
        VALUES (?, ?, ?, ?)
        """,
        (session_id, status, now, now),
    )
    session = get_session(connection, session_id)
    assert session is not None
    return session


def get_session(connection: sqlite3.Connection, session_id: str) -> dict[str, Any] | None:
    row = connection.execute("SELECT * FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
    return row_to_dict(row)


def list_sessions(connection: sqlite3.Connection, *, limit: int) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT *
        FROM chat_sessions
        ORDER BY updated_at DESC, created_at DESC, rowid DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def list_sessions_with_title_context(connection: sqlite3.Connection, *, limit: int) -> list[dict[str, Any]]:
    """查询最近会话并附带首条用户提问与首个原始文件位置，供列表兜底派生标题。"""
    rows = connection.execute(
        """
        SELECT s.*,
               (
                   SELECT m.content
                   FROM chat_messages m
                   JOIN chat_turns t ON t.id = m.turn_id
                   WHERE m.session_id = s.id AND m.role = 'user'
                   ORDER BY t.created_at, t.rowid, m.sequence ASC, m.rowid ASC
                   LIMIT 1
               ) AS first_user_message,
               (
                   SELECT r.location
                   FROM chat_resources r
                   WHERE r.session_id = s.id AND r.type = 'raw'
                   ORDER BY r.created_at, r.rowid
                   LIMIT 1
               ) AS first_raw_location
        FROM chat_sessions s
        ORDER BY s.updated_at DESC, s.created_at DESC, s.rowid DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def set_session_title_if_empty(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    title: str,
) -> dict[str, Any] | None:
    """仅当会话标题仍为空时条件写入标题，避免并发或重复覆盖已有标题。"""
    cursor = connection.execute(
        """
        UPDATE chat_sessions
        SET title = ?
        WHERE id = ? AND (title IS NULL OR trim(title) = '')
        """,
        (title, session_id),
    )
    if cursor.rowcount == 0:
        return None
    return get_session(connection, session_id)


def update_session(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    now: str,
    status: str | None = None,
    active_turn_id: str | None = None,
    clear_active_turn: bool = False,
) -> dict[str, Any]:
    updates: dict[str, Any] = {"updated_at": now}
    if status is not None:
        updates["status"] = status
    if active_turn_id is not None:
        updates["active_turn_id"] = active_turn_id
    if clear_active_turn:
        updates["active_turn_id"] = None
    assignments = ", ".join(f"{name} = ?" for name in updates)
    connection.execute(f"UPDATE chat_sessions SET {assignments} WHERE id = ?", [*updates.values(), session_id])
    session = get_session(connection, session_id)
    assert session is not None
    return session


def list_sessions_needing_recovery(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    """查询持有活跃轮或仍在运行的会话。"""
    rows = connection.execute(
        "SELECT * FROM chat_sessions WHERE active_turn_id IS NOT NULL OR status = 'running'"
    ).fetchall()
    return [dict(row) for row in rows]
