from __future__ import annotations

import sqlite3
from typing import Any

from backend.core.db import row_to_dict
from backend.crud.json_utils import dumps_json


def create_review(
    connection: sqlite3.Connection,
    *,
    review_id: str,
    task_id: str,
    decision: str,
    comment: str | None,
    reviewer: str | None,
    created_at: str,
) -> dict[str, Any]:
    connection.execute(
        """
        INSERT INTO reviews (
            id, task_id, decision, comment, reviewer, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (review_id, task_id, decision, comment, reviewer, created_at),
    )
    connection.commit()
    row = connection.execute("SELECT * FROM reviews WHERE id = ?", (review_id,)).fetchone()
    review = row_to_dict(row)
    assert review is not None
    return review


def create_review_field(
    connection: sqlite3.Connection,
    *,
    review_field_id: str,
    review_id: str,
    task_id: str,
    field_name: str,
    agent_value: Any,
    review_value: Any,
    final_value: Any,
    decision: str,
    comment: str | None,
) -> dict[str, Any]:
    connection.execute(
        """
        INSERT INTO review_fields (
            id, review_id, task_id, field_name, agent_value_json,
            review_value_json, final_value_json, decision, comment
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            review_field_id,
            review_id,
            task_id,
            field_name,
            dumps_json(agent_value) if agent_value is not None else None,
            dumps_json(review_value) if review_value is not None else None,
            dumps_json(final_value) if final_value is not None else None,
            decision,
            comment,
        ),
    )
    connection.commit()
    row = connection.execute(
        "SELECT * FROM review_fields WHERE id = ?",
        (review_field_id,),
    ).fetchone()
    review_field = row_to_dict(row)
    assert review_field is not None
    return review_field


def list_latest_review_fields(
    connection: sqlite3.Connection,
    task_id: str,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT rf.*
        FROM review_fields rf
        JOIN reviews r ON r.id = rf.review_id
        WHERE rf.task_id = ?
        ORDER BY r.created_at DESC, rf.field_name
        """,
        (task_id,),
    ).fetchall()
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for row in rows:
        field = dict(row)
        field_name = field["field_name"]
        if field_name in seen:
            continue
        seen.add(field_name)
        result.append(field)
    return result
