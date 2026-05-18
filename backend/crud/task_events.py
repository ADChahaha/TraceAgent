from __future__ import annotations

import sqlite3
from typing import Any

from backend.core.db import row_to_dict
from backend.crud.json_utils import dumps_json


def create_task_event(
    connection: sqlite3.Connection,
    *,
    event_id: str,
    task_id: str,
    event_type: str,
    status: str,
    stage: str,
    payload: dict[str, Any],
    created_at: str,
) -> dict[str, Any]:
    sequence = get_last_sequence(connection, task_id) + 1
    connection.execute(
        """
        INSERT INTO task_events (
            id, task_id, sequence, event_type, status, stage,
            payload_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            task_id,
            sequence,
            event_type,
            status,
            stage,
            dumps_json(payload),
            created_at,
        ),
    )
    connection.commit()
    row = connection.execute(
        "SELECT * FROM task_events WHERE id = ?",
        (event_id,),
    ).fetchone()
    event = row_to_dict(row)
    assert event is not None
    return event


def list_task_events(
    connection: sqlite3.Connection,
    *,
    task_id: str,
    after_sequence: int = 0,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT *
        FROM task_events
        WHERE task_id = ? AND sequence > ?
        ORDER BY sequence ASC
        """,
        (task_id, after_sequence),
    ).fetchall()
    return [dict(row) for row in rows]


def get_last_sequence(connection: sqlite3.Connection, task_id: str) -> int:
    row = connection.execute(
        "SELECT COALESCE(MAX(sequence), 0) AS last_sequence FROM task_events WHERE task_id = ?",
        (task_id,),
    ).fetchone()
    if row is None:
        return 0
    return int(row["last_sequence"] or 0)
