from __future__ import annotations

import sqlite3
import uuid
from typing import Any

from backend.crud import audit as audit_crud
from backend.crud import extraction as extraction_crud
from backend.crud import tasks as tasks_crud
from backend.crud.json_utils import loads_json
from backend.services.agent_process import (
    build_document_block_lookup,
    serialize_field_agent_process,
)


class AuditService:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def commit_field(
        self,
        *,
        task_id: str,
        field: dict[str, Any],
        trace: dict[str, Any] | None,
        final_value: Any,
        committed_by: str,
        committed_at: str,
    ) -> dict[str, Any]:
        evidence = loads_json(trace["evidence_json"], {}) if trace else {}
        actions = loads_json(trace["actions_json"], []) if trace else []
        related_fields = loads_json(trace["related_fields_json"], []) if trace else []
        action_types = {action.get("action_type") for action in actions}
        return audit_crud.create_field_commit(
            self.connection,
            commit_id=f"commit_{uuid.uuid4().hex}",
            task_id=task_id,
            field_name=field["field_name"],
            final_value=final_value,
            agent_value=loads_json(field["agent_value_json"], None),
            evidence_refs=evidence.get("refs") or [],
            used_global_lookup="global_lookup" in action_types,
            used_validation_rule="validation_rule" in action_types,
            related_fields=related_fields,
            committed_by=committed_by,
            committed_at=committed_at,
        )

    def list_audit(self, task: dict[str, Any]) -> dict[str, Any]:
        commits = audit_crud.list_field_commits(self.connection, task["id"])
        traces = {
            trace["field_name"]: trace
            for trace in extraction_crud.list_field_traces(self.connection, task["id"])
        }
        block_lookup = build_document_block_lookup(
            tasks_crud.list_documents_by_task(self.connection, task["id"])
        )
        return {
            "task_id": task["id"],
            "status": task["status"],
            "field_commits": [
                self._serialize_commit(
                    commit,
                    traces.get(commit["field_name"]),
                    block_lookup=block_lookup,
                )
                for commit in commits
            ],
        }

    def has_commit(self, *, task_id: str, field_name: str) -> bool:
        return audit_crud.field_commit_exists(
            self.connection,
            task_id=task_id,
            field_name=field_name,
        )

    def _serialize_commit(
        self,
        commit: dict[str, Any],
        trace: dict[str, Any] | None,
        *,
        block_lookup: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        agent_value = loads_json(commit["agent_value_json"], None)
        actions = loads_json(trace["actions_json"], []) if trace else []
        return {
            "field_name": commit["field_name"],
            "final_value": loads_json(commit["final_value_json"], None),
            "agent_value": agent_value,
            "evidence_refs": loads_json(commit["evidence_refs_json"], []),
            "used_global_lookup": bool(commit["used_global_lookup"]),
            "used_validation_rule": bool(commit["used_validation_rule"]),
            "action_types": [
                action_type
                for action_type in (action.get("action_type") for action in actions)
                if action_type
            ],
            "related_fields": loads_json(commit["related_fields_json"], []),
            "committed_by": commit["committed_by"],
            "committed_at": commit["committed_at"],
            "agent_process": serialize_field_agent_process(
                trace,
                value=agent_value,
                block_lookup=block_lookup,
            ),
        }
