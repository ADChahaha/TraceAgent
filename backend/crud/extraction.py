from __future__ import annotations

import sqlite3
from typing import Any

from backend.core.db import row_to_dict
from backend.crud.json_utils import dumps_json


def create_agent_run(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    task_id: str,
    agent_status: str,
    failure_reason: str | None,
    request: dict[str, Any],
    result: dict[str, Any],
    trace: dict[str, Any],
    started_at: str,
    finished_at: str,
) -> dict[str, Any]:
    connection.execute(
        """
        INSERT INTO agent_runs (
            id, task_id, agent_status, failure_reason, request_json,
            result_json, trace_json, started_at, finished_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            task_id,
            agent_status,
            failure_reason,
            dumps_json(request),
            dumps_json(result),
            dumps_json(trace),
            started_at,
            finished_at,
        ),
    )
    connection.commit()
    row = connection.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
    agent_run = row_to_dict(row)
    assert agent_run is not None
    return agent_run


def get_latest_agent_run(
    connection: sqlite3.Connection,
    task_id: str,
) -> dict[str, Any] | None:
    row = connection.execute(
        "SELECT * FROM agent_runs WHERE task_id = ? ORDER BY started_at DESC LIMIT 1",
        (task_id,),
    ).fetchone()
    return row_to_dict(row)


def create_extracted_field(
    connection: sqlite3.Connection,
    *,
    field_id: str,
    task_id: str,
    field_name: str,
    display_name: str,
    field_type: str,
    agent_status: str,
    agent_value: Any,
    reason: str | None,
    failure_reason: str | None,
    now: str,
) -> dict[str, Any]:
    connection.execute(
        """
        INSERT INTO extracted_fields (
            id, task_id, field_name, display_name, field_type, agent_status,
            agent_value_json, final_value_json, source, reason, failure_reason,
            created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            field_id,
            task_id,
            field_name,
            display_name,
            field_type,
            agent_status,
            dumps_json(agent_value) if agent_value is not None else None,
            None,
            "none",
            reason,
            failure_reason,
            now,
            now,
        ),
    )
    connection.commit()
    row = connection.execute(
        "SELECT * FROM extracted_fields WHERE id = ?",
        (field_id,),
    ).fetchone()
    field = row_to_dict(row)
    assert field is not None
    return field


def create_field_trace(
    connection: sqlite3.Connection,
    *,
    trace_id: str,
    task_id: str,
    field_name: str,
    evidence: dict[str, Any],
    related_fields: list[str],
    actions: list[dict[str, Any]],
    trace_status: str,
    reason: str | None,
    failure_reason: str | None,
) -> dict[str, Any]:
    connection.execute(
        """
        INSERT INTO field_traces (
            id, task_id, field_name, evidence_json, related_fields_json,
            actions_json, trace_status, reason, failure_reason
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            trace_id,
            task_id,
            field_name,
            dumps_json(evidence),
            dumps_json(related_fields),
            dumps_json(actions),
            trace_status,
            reason,
            failure_reason,
        ),
    )
    connection.commit()
    row = connection.execute(
        "SELECT * FROM field_traces WHERE id = ?",
        (trace_id,),
    ).fetchone()
    trace = row_to_dict(row)
    assert trace is not None
    return trace


def list_extracted_fields(
    connection: sqlite3.Connection,
    task_id: str,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT * FROM extracted_fields WHERE task_id = ? ORDER BY created_at, field_name",
        (task_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def list_field_traces(
    connection: sqlite3.Connection,
    task_id: str,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT * FROM field_traces WHERE task_id = ? ORDER BY field_name",
        (task_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def update_field_final_value(
    connection: sqlite3.Connection,
    *,
    task_id: str,
    field_name: str,
    final_value: Any,
    source: str,
    now: str,
) -> None:
    connection.execute(
        """
        UPDATE extracted_fields
        SET final_value_json = ?, source = ?, updated_at = ?
        WHERE task_id = ? AND field_name = ?
        """,
        (
            dumps_json(final_value) if final_value is not None else None,
            source,
            now,
            task_id,
            field_name,
        ),
    )
    connection.commit()
