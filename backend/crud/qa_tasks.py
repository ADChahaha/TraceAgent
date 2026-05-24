from __future__ import annotations

import sqlite3
from typing import Any

from backend.core.db import row_to_dict
from backend.crud.json_utils import dumps_json


def create_task(
    connection: sqlite3.Connection,
    *,
    task_id: str,
    metadata: dict[str, Any],
    now: str,
) -> dict[str, Any]:
    connection.execute(
        """
        INSERT INTO qa_tasks (
            id, status, stage, metadata_json, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            task_id,
            "processing",
            "document_processing",
            dumps_json(metadata),
            now,
            now,
        ),
    )
    connection.commit()
    task = get_task(connection, task_id)
    assert task is not None
    return task


def get_task(connection: sqlite3.Connection, task_id: str) -> dict[str, Any] | None:
    row = connection.execute("SELECT * FROM qa_tasks WHERE id = ?", (task_id,)).fetchone()
    return row_to_dict(row)


def list_tasks(connection: sqlite3.Connection, *, limit: int) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT *
        FROM qa_tasks
        ORDER BY updated_at DESC, created_at DESC, rowid DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def update_task(
    connection: sqlite3.Connection,
    *,
    task_id: str,
    now: str,
    status: str | None = None,
    stage: str | None = None,
    active_turn_id: str | None = None,
    clear_active_turn: bool = False,
    error_message: str | None = None,
) -> dict[str, Any]:
    updates: dict[str, Any] = {"updated_at": now}
    if status is not None:
        updates["status"] = status
    if stage is not None:
        updates["stage"] = stage
    if active_turn_id is not None:
        updates["active_turn_id"] = active_turn_id
    if clear_active_turn:
        updates["active_turn_id"] = None
    if error_message is not None:
        updates["error_message"] = error_message
    assignments = ", ".join(f"{name} = ?" for name in updates)
    connection.execute(f"UPDATE qa_tasks SET {assignments} WHERE id = ?", [*updates.values(), task_id])
    connection.commit()
    task = get_task(connection, task_id)
    assert task is not None
    return task


def create_document(
    connection: sqlite3.Connection,
    *,
    document_id: str,
    task_id: str,
    filename: str,
    file_type: str,
    content_type: str | None,
    upload_size_bytes: int,
    upload_sha256: str,
    html: str,
    display_html: str,
    markdown: str,
    md_list: list[Any],
    blocks: list[dict[str, Any]],
    processor_meta: dict[str, Any],
    warnings: list[Any],
    now: str,
) -> dict[str, Any]:
    connection.execute(
        """
        INSERT INTO qa_documents (
            id, task_id, filename, file_type, content_type, upload_size_bytes,
            upload_sha256, html, display_html, markdown, md_list_json,
            blocks_json, processor_meta_json, warnings_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            document_id,
            task_id,
            filename,
            file_type,
            content_type,
            upload_size_bytes,
            upload_sha256,
            html,
            display_html,
            markdown,
            dumps_json(md_list),
            dumps_json(blocks),
            dumps_json(processor_meta),
            dumps_json(warnings),
            now,
        ),
    )
    connection.commit()
    row = connection.execute("SELECT * FROM qa_documents WHERE id = ?", (document_id,)).fetchone()
    document = row_to_dict(row)
    assert document is not None
    return document


def list_documents(connection: sqlite3.Connection, task_id: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT * FROM qa_documents WHERE task_id = ? ORDER BY created_at, rowid",
        (task_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def create_message(
    connection: sqlite3.Connection,
    *,
    message_id: str,
    task_id: str,
    turn_id: str | None,
    role: str,
    content: str,
    metadata: dict[str, Any],
    now: str,
) -> dict[str, Any]:
    connection.execute(
        """
        INSERT INTO qa_messages (
            id, task_id, turn_id, role, content, metadata_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (message_id, task_id, turn_id, role, content, dumps_json(metadata), now),
    )
    connection.commit()
    row = connection.execute("SELECT * FROM qa_messages WHERE id = ?", (message_id,)).fetchone()
    message = row_to_dict(row)
    assert message is not None
    return message


def list_messages(connection: sqlite3.Connection, task_id: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT * FROM qa_messages WHERE task_id = ? ORDER BY created_at, rowid",
        (task_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def create_turn(
    connection: sqlite3.Connection,
    *,
    turn_id: str,
    task_id: str,
    user_message_id: str,
    status: str,
    now: str,
) -> dict[str, Any]:
    connection.execute(
        """
        INSERT INTO qa_turns (
            id, task_id, status, user_message_id, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (turn_id, task_id, status, user_message_id, now, now),
    )
    connection.commit()
    turn = get_turn(connection, turn_id)
    assert turn is not None
    return turn


def get_turn(connection: sqlite3.Connection, turn_id: str) -> dict[str, Any] | None:
    row = connection.execute("SELECT * FROM qa_turns WHERE id = ?", (turn_id,)).fetchone()
    return row_to_dict(row)


def get_active_turn(connection: sqlite3.Connection, task_id: str) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT *
        FROM qa_turns
        WHERE task_id = ? AND status IN ('queued', 'in_progress', 'cancelling')
        ORDER BY created_at DESC, rowid DESC
        LIMIT 1
        """,
        (task_id,),
    ).fetchone()
    return row_to_dict(row)


def update_turn(
    connection: sqlite3.Connection,
    *,
    turn_id: str,
    now: str,
    status: str | None = None,
    agent_completion_id: str | None = None,
    error_message: str | None = None,
    completed_at: str | None = None,
) -> dict[str, Any]:
    updates: dict[str, Any] = {"updated_at": now}
    if status is not None:
        updates["status"] = status
    if agent_completion_id is not None:
        updates["agent_completion_id"] = agent_completion_id
    if error_message is not None:
        updates["error_message"] = error_message
    if completed_at is not None:
        updates["completed_at"] = completed_at
    assignments = ", ".join(f"{name} = ?" for name in updates)
    connection.execute(f"UPDATE qa_turns SET {assignments} WHERE id = ?", [*updates.values(), turn_id])
    connection.commit()
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
    error_message: str | None = None,
    completed_at: str | None = None,
) -> dict[str, Any] | None:
    updates: dict[str, Any] = {"status": status, "updated_at": now}
    if error_message is not None:
        updates["error_message"] = error_message
    if completed_at is not None:
        updates["completed_at"] = completed_at
    placeholders = ", ".join("?" for _ in current_statuses)
    assignments = ", ".join(f"{name} = ?" for name in updates)
    cursor = connection.execute(
        f"""
        UPDATE qa_turns
        SET {assignments}
        WHERE id = ? AND status IN ({placeholders})
        """,
        [*updates.values(), turn_id, *sorted(current_statuses)],
    )
    connection.commit()
    if cursor.rowcount == 0:
        return None
    return get_turn(connection, turn_id)


def create_event(
    connection: sqlite3.Connection,
    *,
    event_id: str,
    task_id: str,
    turn_id: str | None,
    event_type: str,
    status: str,
    stage: str,
    payload: dict[str, Any],
    now: str,
) -> dict[str, Any]:
    sequence = get_last_event_sequence(connection, task_id) + 1
    connection.execute(
        """
        INSERT INTO qa_events (
            id, task_id, turn_id, sequence, event_type, status, stage,
            payload_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (event_id, task_id, turn_id, sequence, event_type, status, stage, dumps_json(payload), now),
    )
    connection.commit()
    row = connection.execute("SELECT * FROM qa_events WHERE id = ?", (event_id,)).fetchone()
    event = row_to_dict(row)
    assert event is not None
    return event


def list_events(connection: sqlite3.Connection, task_id: str, *, after_sequence: int = 0) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT *
        FROM qa_events
        WHERE task_id = ? AND sequence > ?
        ORDER BY sequence ASC
        """,
        (task_id, after_sequence),
    ).fetchall()
    return [dict(row) for row in rows]


def get_last_event_sequence(connection: sqlite3.Connection, task_id: str) -> int:
    row = connection.execute(
        "SELECT COALESCE(MAX(sequence), 0) AS last_sequence FROM qa_events WHERE task_id = ?",
        (task_id,),
    ).fetchone()
    if row is None:
        return 0
    return int(row["last_sequence"] or 0)
