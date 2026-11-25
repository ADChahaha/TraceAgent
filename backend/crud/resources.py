"""会话资源引用表（chat_resources）读写函数。"""

from __future__ import annotations

import sqlite3
from typing import Any

from backend.core.db import row_to_dict


def create_resource(
    connection: sqlite3.Connection,
    *,
    resource_id: str,
    session_id: str,
    resource_type: str,
    location: str,
    now: str,
    size_bytes: int = 0,
) -> dict[str, Any]:
    connection.execute(
        """
        INSERT INTO chat_resources (
            id, session_id, type, location, size_bytes, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (resource_id, session_id, resource_type, location, size_bytes, now),
    )
    row = connection.execute("SELECT * FROM chat_resources WHERE id = ?", (resource_id,)).fetchone()
    resource = row_to_dict(row)
    assert resource is not None
    return resource


def get_resource(connection: sqlite3.Connection, resource_id: str) -> dict[str, Any] | None:
    row = connection.execute("SELECT * FROM chat_resources WHERE id = ?", (resource_id,)).fetchone()
    return row_to_dict(row)


def delete_resource(connection: sqlite3.Connection, resource_id: str) -> None:
    """按资源 ID 删除一行；由调用方校验资源归属会话。"""
    connection.execute("DELETE FROM chat_resources WHERE id=?", (resource_id,))


def list_resources(
    connection: sqlite3.Connection,
    session_id: str,
    *,
    resource_type: str | None = None,
) -> list[dict[str, Any]]:
    if resource_type is None:
        rows = connection.execute(
            "SELECT * FROM chat_resources WHERE session_id = ? ORDER BY created_at, rowid",
            (session_id,),
        ).fetchall()
    else:
        rows = connection.execute(
            "SELECT * FROM chat_resources WHERE session_id = ? AND type = ? ORDER BY created_at, rowid",
            (session_id, resource_type),
        ).fetchall()
    return [dict(row) for row in rows]


def delete_resources(connection: sqlite3.Connection, session_id: str) -> None:
    """删除会话资源引用。"""
    connection.execute("DELETE FROM chat_resources WHERE session_id=?", (session_id,))
