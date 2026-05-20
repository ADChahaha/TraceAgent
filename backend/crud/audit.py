from __future__ import annotations

import sqlite3
from typing import Any

from backend.core.db import row_to_dict
from backend.crud.json_utils import dumps_json


def create_field_commit(
    connection: sqlite3.Connection,
    *,
    commit_id: str,
    task_id: str,
    field_name: str,
    final_value: Any,
    agent_value: Any,
    evidence_refs: list[dict[str, Any]],
    used_global_lookup: bool,
    used_validation_rule: bool,
    related_fields: list[str],
    committed_by: str,
    committed_at: str,
) -> dict[str, Any]:
    connection.execute(
        """
        INSERT INTO field_commits (
            id, task_id, field_name, final_value_json, agent_value_json,
            evidence_refs_json, used_global_lookup, used_validation_rule,
            related_fields_json, committed_by, committed_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            commit_id,
            task_id,
            field_name,
            dumps_json(final_value) if final_value is not None else None,
            dumps_json(agent_value) if agent_value is not None else None,
            dumps_json(evidence_refs),
            1 if used_global_lookup else 0,
            1 if used_validation_rule else 0,
            dumps_json(related_fields),
            committed_by,
            committed_at,
        ),
    )
    connection.commit()
    row = connection.execute(
        "SELECT * FROM field_commits WHERE id = ?",
        (commit_id,),
    ).fetchone()
    commit = row_to_dict(row)
    assert commit is not None
    return commit


def list_field_commits(
    connection: sqlite3.Connection,
    task_id: str,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT * FROM field_commits WHERE task_id = ? ORDER BY committed_at, field_name",
        (task_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def field_commit_exists(
    connection: sqlite3.Connection,
    *,
    task_id: str,
    field_name: str,
) -> bool:
    row = connection.execute(
        """
        SELECT 1 FROM field_commits
        WHERE task_id = ? AND field_name = ?
        LIMIT 1
        """,
        (task_id, field_name),
    ).fetchone()
    return row is not None
