from __future__ import annotations

import sqlite3
from typing import Any

from backend.core.db import row_to_dict
from backend.crud.json_utils import dumps_json


def create_task(
    connection: sqlite3.Connection,
    *,
    task_id: str,
    task_type: str,
    metadata: dict[str, Any],
    now: str,
) -> dict[str, Any]:
    connection.execute(
        """
        INSERT INTO tasks (
            id, task_type, status, stage, metadata_json, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            task_id,
            task_type,
            "pending",
            "uploaded",
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
    row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return row_to_dict(row)


def update_task(
    connection: sqlite3.Connection,
    *,
    task_id: str,
    now: str,
    status: str | None = None,
    stage: str | None = None,
    route: str | None = None,
    route_reason: str | None = None,
    error_message: str | None = None,
    completed_at: str | None = None,
) -> dict[str, Any]:
    updates: dict[str, Any] = {"updated_at": now}
    if status is not None:
        updates["status"] = status
    if stage is not None:
        updates["stage"] = stage
    if route is not None:
        updates["route"] = route
    if route_reason is not None:
        updates["route_reason"] = route_reason
    if error_message is not None:
        updates["error_message"] = error_message
    if completed_at is not None:
        updates["completed_at"] = completed_at

    assignments = ", ".join(f"{name} = ?" for name in updates)
    params = [*updates.values(), task_id]
    connection.execute(f"UPDATE tasks SET {assignments} WHERE id = ?", params)
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
    markdown: str,
    md_list: list[str],
    blocks: list[dict[str, Any]],
    processor_meta: dict[str, Any],
    warnings: list[str],
    now: str,
) -> dict[str, Any]:
    connection.execute(
        """
        INSERT INTO documents (
            id, task_id, filename, file_type, content_type, upload_size_bytes,
            upload_sha256, markdown, md_list_json, blocks_json,
            processor_meta_json, warnings_json, processed_at, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            document_id,
            task_id,
            filename,
            file_type,
            content_type,
            upload_size_bytes,
            upload_sha256,
            markdown,
            dumps_json(md_list),
            dumps_json(blocks),
            dumps_json(processor_meta),
            dumps_json(warnings),
            now,
            now,
        ),
    )
    connection.commit()
    row = connection.execute(
        "SELECT * FROM documents WHERE id = ?",
        (document_id,),
    ).fetchone()
    document = row_to_dict(row)
    assert document is not None
    return document


def get_document_by_task(
    connection: sqlite3.Connection,
    task_id: str,
) -> dict[str, Any] | None:
    row = connection.execute(
        "SELECT * FROM documents WHERE task_id = ? ORDER BY created_at DESC LIMIT 1",
        (task_id,),
    ).fetchone()
    return row_to_dict(row)


def list_documents_by_task(
    connection: sqlite3.Connection,
    task_id: str,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT * FROM documents WHERE task_id = ? ORDER BY created_at, rowid",
        (task_id,),
    ).fetchall()
    return [dict(row) for row in rows]
