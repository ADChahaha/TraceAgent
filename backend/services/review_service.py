from __future__ import annotations

import sqlite3
import uuid
from typing import Any

from backend.crud import extraction as extraction_crud
from backend.crud import reviews as reviews_crud
from backend.crud import tasks as tasks_crud
from backend.crud.json_utils import loads_json
from backend.services.agent_process import serialize_field_agent_process
from backend.services.audit_service import AuditService
from backend.services.errors import ConflictError, NotFoundError, ValidationError
from backend.services.time_utils import utc_now


class ReviewService:
    def __init__(
        self,
        *,
        connection: sqlite3.Connection,
        audit_service: AuditService,
    ):
        self.connection = connection
        self.audit_service = audit_service

    def get_review_handoff(self, task_id: str) -> dict[str, Any]:
        task = self._get_task(task_id)
        if task["status"] != "waiting_review":
            raise ConflictError(f"task is not waiting_review: {task_id}")
        fields = extraction_crud.list_extracted_fields(self.connection, task_id)
        traces = {
            trace["field_name"]: trace
            for trace in extraction_crud.list_field_traces(self.connection, task_id)
        }
        routes = [
            route
            for route in extraction_crud.list_field_routes(self.connection, task_id)
            if bool(route["needs_review"])
        ]
        return {
            "task_id": task["id"],
            "status": task["status"],
            "route": task["route"],
            "route_reason": task["route_reason"],
            "fields": [
                self._build_handoff_field(
                    field,
                    traces.get(field["field_name"]),
                    route,
                )
                for route in routes
                for field in fields
                if field["field_name"] == route["field_name"]
            ],
        }

    def submit_review(
        self,
        *,
        task_id: str,
        decision: str,
        fields: list[dict[str, Any]],
        comment: str | None,
        reviewer: str | None,
    ) -> dict[str, Any]:
        if decision not in {"approve", "revise_and_approve", "reject"}:
            raise ValidationError(f"unsupported review decision: {decision}")
        task = self._get_task(task_id)
        if task["status"] != "waiting_review":
            raise ConflictError(f"task is not waiting_review: {task_id}")

        field_by_name = {
            field["field_name"]: field
            for field in extraction_crud.list_extracted_fields(self.connection, task_id)
        }
        trace_by_name = {
            trace["field_name"]: trace
            for trace in extraction_crud.list_field_traces(self.connection, task_id)
        }
        review_routes = [
            route
            for route in extraction_crud.list_field_routes(self.connection, task_id)
            if bool(route["needs_review"])
        ]
        route_by_name = {route["field_name"]: route for route in review_routes}
        submitted_by_name = {field["field_name"]: field for field in fields}
        reviewed_at = utc_now()
        review = reviews_crud.create_review(
            self.connection,
            review_id=f"review_{uuid.uuid4().hex}",
            task_id=task_id,
            decision=decision,
            comment=comment,
            reviewer=reviewer,
            created_at=reviewed_at,
        )

        if decision == "reject":
            for route in review_routes:
                field = field_by_name[route["field_name"]]
                reviews_crud.create_review_field(
                    self.connection,
                    review_field_id=f"review_field_{uuid.uuid4().hex}",
                    review_id=review["id"],
                    task_id=task_id,
                    field_name=field["field_name"],
                    agent_value=loads_json(field["agent_value_json"], None),
                    review_value=None,
                    final_value=None,
                    decision=decision,
                    comment=comment,
                )
            task = tasks_crud.update_task(
                self.connection,
                task_id=task_id,
                status="rejected",
                stage="done",
                completed_at=reviewed_at,
                now=reviewed_at,
            )
            return self._serialize_review_response(task, decision)

        for route in review_routes:
            field = field_by_name[route["field_name"]]
            submitted_field = submitted_by_name.get(field["field_name"], {})
            agent_value = loads_json(field["agent_value_json"], None)
            if decision == "approve":
                review_value = None
                final_value = agent_value
                source = "agent"
            else:
                if "review_value" not in submitted_field:
                    raise ValidationError(
                        f"review_value is required for field: {field['field_name']}"
                    )
                review_value = submitted_field["review_value"]
                final_value = review_value
                source = "human"

            extraction_crud.update_field_final_value(
                self.connection,
                task_id=task_id,
                field_name=field["field_name"],
                final_value=final_value,
                source=source,
                now=reviewed_at,
            )
            reviews_crud.create_review_field(
                self.connection,
                review_field_id=f"review_field_{uuid.uuid4().hex}",
                review_id=review["id"],
                task_id=task_id,
                field_name=field["field_name"],
                agent_value=agent_value,
                review_value=review_value,
                final_value=final_value,
                decision=decision,
                comment=submitted_field.get("comment") or comment,
            )
            self.audit_service.commit_field(
                task_id=task_id,
                field=field,
                trace=trace_by_name.get(field["field_name"]),
                route=route_by_name[field["field_name"]],
                final_value=final_value,
                reviewed=True,
                review_decision=decision,
                review_value=review_value,
                committed_by="human",
                committed_at=reviewed_at,
            )

        task = tasks_crud.update_task(
            self.connection,
            task_id=task_id,
            status="completed",
            stage="done",
            completed_at=reviewed_at,
            now=reviewed_at,
        )
        return self._serialize_review_response(task, decision)

    def _get_task(self, task_id: str) -> dict[str, Any]:
        task = tasks_crud.get_task(self.connection, task_id)
        if task is None:
            raise NotFoundError(f"task not found: {task_id}")
        return task

    def _build_handoff_field(
        self,
        field: dict[str, Any],
        trace: dict[str, Any] | None,
        route: dict[str, Any],
    ) -> dict[str, Any]:
        evidence = loads_json(trace["evidence_json"], {}) if trace else {}
        actions = loads_json(trace["actions_json"], []) if trace else []
        return {
            "field_name": field["field_name"],
            "display_name": field["display_name"],
            "agent_value": loads_json(field["agent_value_json"], None),
            "field_status": field["agent_status"],
            "needs_review": bool(route["needs_review"]),
            "review_reason": route["route_reason"],
            "evidence_texts": evidence.get("texts") or [],
            "evidence_refs": evidence.get("refs") or [],
            "related_fields": loads_json(trace["related_fields_json"], []) if trace else [],
            "actions": [action.get("action_type") for action in actions],
            "reason": trace["reason"] if trace else None,
            "failure_reason": trace["failure_reason"] if trace else None,
            "agent_process": serialize_field_agent_process(trace),
        }

    def _serialize_review_response(
        self,
        task: dict[str, Any],
        decision: str,
    ) -> dict[str, Any]:
        return {
            "task_id": task["id"],
            "status": task["status"],
            "stage": task["stage"],
            "review_decision": decision,
        }
