from __future__ import annotations

import sqlite3
from typing import Any

from backend.core.db import row_to_dict
from backend.crud.json_utils import dumps_json


def create_agent_stage_run(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    task_id: str,
    sequence: int,
    stage: str,
    agent_name: str,
    status: str,
    failure_reason: str | None,
    request: dict[str, Any],
    response: dict[str, Any],
    trace: dict[str, Any],
    started_at: str,
    finished_at: str,
) -> dict[str, Any]:
    connection.execute(
        """
        INSERT INTO agent_stage_runs (
            id, task_id, sequence, stage, agent_name, status, failure_reason,
            request_json, response_json, trace_json, started_at, finished_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            task_id,
            sequence,
            stage,
            agent_name,
            status,
            failure_reason,
            dumps_json(request),
            dumps_json(response),
            dumps_json(trace),
            started_at,
            finished_at,
        ),
    )
    connection.commit()
    row = connection.execute(
        "SELECT * FROM agent_stage_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    stage_run = row_to_dict(row)
    assert stage_run is not None
    return stage_run


def list_agent_stage_runs(
    connection: sqlite3.Connection,
    task_id: str,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT * FROM agent_stage_runs WHERE task_id = ? ORDER BY sequence, started_at, rowid",
        (task_id,),
    ).fetchall()
    return [dict(row) for row in rows]
