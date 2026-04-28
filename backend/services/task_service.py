from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from typing import Any

from backend.core.config import BackendSettings
from backend.core.storage import compute_sha256
from backend.crud import audit as audit_crud
from backend.crud import extraction as extraction_crud
from backend.crud import reviews as reviews_crud
from backend.crud import tasks as tasks_crud
from backend.crud.json_utils import loads_json
from backend.services.audit_service import AuditService
from backend.services.errors import AgentServiceError, NotFoundError, ValidationError
from backend.services.route_policy import build_route_policy_request
from backend.services.time_utils import utc_now


class TaskService:
    def __init__(
        self,
        *,
        connection: sqlite3.Connection,
        settings: BackendSettings,
        agent_client,
        audit_service: AuditService,
    ):
        self.connection = connection
        self.settings = settings
        self.agent_client = agent_client
        self.audit_service = audit_service

    def create_task(
        self,
        *,
        file_bytes: bytes,
        filename: str,
        content_type: str | None,
        task_type: str,
        task_spec: dict[str, Any] | None,
        metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
        file_type = self._infer_file_type(filename)
        resolved_task_spec = self._resolve_task_spec(task_type, task_spec)
        metadata = metadata or {}
        now = utc_now()
        task_id = f"task_{uuid.uuid4().hex}"
        document_id = f"doc_{uuid.uuid4().hex}"
        tasks_crud.create_task(
            self.connection,
            task_id=task_id,
            task_type=task_type,
            metadata=metadata,
            now=now,
        )

        try:
            task = self._run_agent_pipeline(
                task_id=task_id,
                document_id=document_id,
                file_bytes=file_bytes,
                filename=filename,
                content_type=content_type,
                file_type=file_type,
                task_type=task_type,
                task_spec=resolved_task_spec,
                metadata=metadata,
            )
        except Exception as exc:
            failed_at = utc_now()
            tasks_crud.update_task(
                self.connection,
                task_id=task_id,
                status="failed",
                stage="done",
                error_message=str(exc),
                completed_at=failed_at,
                now=failed_at,
            )
            if isinstance(exc, (ValidationError, AgentServiceError)):
                raise
            raise AgentServiceError(str(exc)) from exc

        return self.serialize_created_task(task)

    def get_task_summary(self, task_id: str) -> dict[str, Any]:
        task = self.get_task_or_raise(task_id)
        fields = extraction_crud.list_extracted_fields(self.connection, task_id)
        traces = extraction_crud.list_field_traces(self.connection, task_id)
        routes = extraction_crud.list_field_routes(self.connection, task_id)
        needs_review = task["status"] == "waiting_review" or any(
            bool(route["needs_review"]) for route in routes
        )
        return {
            "task_id": task["id"],
            "status": task["status"],
            "stage": task["stage"],
            "route": task["route"],
            "route_reason": task["route_reason"],
            "has_result": bool(fields),
            "has_trace": bool(traces),
            "needs_review": needs_review,
            "created_at": task["created_at"],
            "updated_at": task["updated_at"],
        }

    def get_result(self, task_id: str) -> dict[str, Any]:
        task = self.get_task_or_raise(task_id)
        fields = extraction_crud.list_extracted_fields(self.connection, task_id)
        routes = {
            route["field_name"]: route
            for route in extraction_crud.list_field_routes(self.connection, task_id)
        }
        review_fields = {
            field["field_name"]: field
            for field in reviews_crud.list_latest_review_fields(self.connection, task_id)
        }
        committed_fields = {
            commit["field_name"]
            for commit in audit_crud.list_field_commits(self.connection, task_id)
        }
        return {
            "task_id": task["id"],
            "status": task["status"],
            "route": task["route"],
            "fields": [
                self._serialize_result_field(
                    field,
                    routes.get(field["field_name"]),
                    review_fields.get(field["field_name"]),
                    field["field_name"] in committed_fields,
                )
                for field in fields
            ],
        }

    def get_trace(self, task_id: str) -> dict[str, Any]:
        task = self.get_task_or_raise(task_id)
        agent_run = extraction_crud.get_latest_agent_run(self.connection, task_id)
        traces = extraction_crud.list_field_traces(self.connection, task_id)
        trace_payload = loads_json(agent_run["trace_json"], {}) if agent_run else {}
        return {
            "task_id": task["id"],
            "agent_status": agent_run["agent_status"] if agent_run else None,
            "failure_reason": agent_run["failure_reason"] if agent_run else None,
            "fields": [self._serialize_trace_field(trace) for trace in traces],
            "metadata": trace_payload.get("metadata", {}),
        }

    def get_task_or_raise(self, task_id: str) -> dict[str, Any]:
        task = tasks_crud.get_task(self.connection, task_id)
        if task is None:
            raise NotFoundError(f"task not found: {task_id}")
        return task

    def serialize_created_task(self, task: dict[str, Any]) -> dict[str, Any]:
        return {
            "task_id": task["id"],
            "status": task["status"],
            "stage": task["stage"],
        }

    def _run_agent_pipeline(
        self,
        *,
        task_id: str,
        document_id: str,
        file_bytes: bytes,
        filename: str,
        content_type: str | None,
        file_type: str,
        task_type: str,
        task_spec: dict[str, Any],
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        now = utc_now()
        tasks_crud.update_task(
            self.connection,
            task_id=task_id,
            status="processing",
            stage="document_processing",
            now=now,
        )
        document_result = self.agent_client.process_document(
            file_bytes=file_bytes,
            filename=filename,
            content_type=content_type,
            file_type=file_type,
        )
        blocks = self._normalize_blocks(
            document_id=document_id,
            raw_blocks=document_result.get("blocks") or [],
            markdown=document_result.get("markdown") or "",
        )
        document_saved_at = utc_now()
        tasks_crud.create_document(
            self.connection,
            document_id=document_id,
            task_id=task_id,
            filename=filename,
            file_type=file_type,
            content_type=content_type,
            upload_size_bytes=len(file_bytes),
            upload_sha256=compute_sha256(file_bytes),
            markdown=document_result.get("markdown") or "",
            md_list=document_result.get("md_list") or [],
            blocks=blocks,
            processor_meta=document_result.get("meta_info") or {},
            warnings=document_result.get("warnings") or [],
            now=document_saved_at,
        )

        extraction_started_at = utc_now()
        tasks_crud.update_task(
            self.connection,
            task_id=task_id,
            stage="extraction",
            now=extraction_started_at,
        )
        extraction_result = self.agent_client.extract_fields(
            blocks=blocks,
            markdown=document_result.get("markdown") or "",
            md_list=document_result.get("md_list") or [],
            task_spec=task_spec,
            metadata={
                **metadata,
                "task_id": task_id,
                "task_type": task_type,
                "document_id": document_id,
            },
            run_options=None,
        )
        extraction_finished_at = utc_now()
        extraction_crud.create_agent_run(
            self.connection,
            run_id=f"run_{uuid.uuid4().hex}",
            task_id=task_id,
            agent_status=extraction_result.get("status") or "completed",
            failure_reason=extraction_result.get("failure_reason"),
            request={
                "task_spec": task_spec,
                "metadata": metadata,
                "document_id": document_id,
            },
            result=extraction_result.get("result") or {},
            trace=extraction_result.get("trace") or {},
            started_at=extraction_started_at,
            finished_at=extraction_finished_at,
        )
        if extraction_result.get("status") == "failed":
            return tasks_crud.update_task(
                self.connection,
                task_id=task_id,
                status="failed",
                stage="done",
                error_message=extraction_result.get("failure_reason"),
                completed_at=extraction_finished_at,
                now=extraction_finished_at,
            )

        self._save_extraction_result(
            task_id=task_id,
            task_spec=task_spec,
            extraction_result=extraction_result,
            now=extraction_finished_at,
        )
        fields = extraction_crud.list_extracted_fields(self.connection, task_id)
        traces = extraction_crud.list_field_traces(self.connection, task_id)

        route_started_at = utc_now()
        tasks_crud.update_task(
            self.connection,
            task_id=task_id,
            stage="route_policy",
            now=route_started_at,
        )
        route_request = build_route_policy_request(
            task_spec=task_spec,
            extracted_fields=fields,
            field_traces=traces,
            metadata={
                **metadata,
                "task_id": task_id,
                "task_type": task_type,
                "document_id": document_id,
            },
        )
        route_result = self.agent_client.evaluate_route_policy(**route_request)
        if route_result.get("status") == "failed":
            failed_at = utc_now()
            return tasks_crud.update_task(
                self.connection,
                task_id=task_id,
                status="failed",
                stage="done",
                error_message=route_result.get("failure_reason"),
                completed_at=failed_at,
                now=failed_at,
            )
        routes = self._save_field_routes(
            task_id=task_id,
            field_routes=route_result.get("field_routes") or [],
            now=utc_now(),
        )
        return self._apply_route_outcome(
            task_id=task_id,
            fields=fields,
            traces=traces,
            routes=routes,
        )

    def _save_extraction_result(
        self,
        *,
        task_id: str,
        task_spec: dict[str, Any],
        extraction_result: dict[str, Any],
        now: str,
    ) -> None:
        field_specs = {
            field["field_name"]: field for field in task_spec.get("fields", [])
        }
        trace_by_field = {
            trace["field_name"]: trace
            for trace in (extraction_result.get("trace") or {}).get("fields", [])
        }
        for field in (extraction_result.get("result") or {}).get("fields", []):
            field_name = field["field_name"]
            field_spec = field_specs.get(field_name, {})
            trace = trace_by_field.get(field_name, {})
            extraction_crud.create_extracted_field(
                self.connection,
                field_id=f"field_{uuid.uuid4().hex}",
                task_id=task_id,
                field_name=field_name,
                display_name=field_spec.get("display_name") or field_name,
                field_type=field_spec.get("type") or "string",
                agent_status=field.get("status") or "failed",
                agent_value=field.get("value"),
                reason=trace.get("reason"),
                failure_reason=field.get("failure_reason") or trace.get("failure_reason"),
                now=now,
            )
            extraction_crud.create_field_trace(
                self.connection,
                trace_id=f"trace_{uuid.uuid4().hex}",
                task_id=task_id,
                field_name=field_name,
                evidence=trace.get("evidence") or {},
                related_fields=trace.get("related_fields") or [],
                actions=trace.get("actions") or [],
                trace_status=trace.get("status") or field.get("status") or "failed",
                reason=trace.get("reason"),
                failure_reason=trace.get("failure_reason"),
            )

    def _save_field_routes(
        self,
        *,
        task_id: str,
        field_routes: list[dict[str, Any]],
        now: str,
    ) -> list[dict[str, Any]]:
        saved_routes = []
        for route in field_routes:
            route_name = route["route"]
            saved_routes.append(
                extraction_crud.create_field_route(
                    self.connection,
                    route_id=f"route_{uuid.uuid4().hex}",
                    task_id=task_id,
                    field_name=route["field_name"],
                    route=route_name,
                    route_reason=route["route_reason"],
                    needs_review=route.get("needs_review", route_name != "accept"),
                    now=now,
                )
            )
        return saved_routes

    def _apply_route_outcome(
        self,
        *,
        task_id: str,
        fields: list[dict[str, Any]],
        traces: list[dict[str, Any]],
        routes: list[dict[str, Any]],
    ) -> dict[str, Any]:
        route_summary = self._summarize_routes(routes)
        route_reason = self._summarize_route_reason(routes)
        field_by_name = {field["field_name"]: field for field in fields}
        trace_by_name = {trace["field_name"]: trace for trace in traces}

        if route_summary == "accept":
            committed_at = utc_now()
            for route in routes:
                field = field_by_name[route["field_name"]]
                final_value = loads_json(field["agent_value_json"], None)
                extraction_crud.update_field_final_value(
                    self.connection,
                    task_id=task_id,
                    field_name=field["field_name"],
                    final_value=final_value,
                    source="agent",
                    now=committed_at,
                )
                self.audit_service.commit_field(
                    task_id=task_id,
                    field=field,
                    trace=trace_by_name.get(field["field_name"]),
                    route=route,
                    final_value=final_value,
                    reviewed=False,
                    review_decision=None,
                    review_value=None,
                    committed_by="agent",
                    committed_at=committed_at,
                )
            return tasks_crud.update_task(
                self.connection,
                task_id=task_id,
                status="completed",
                stage="done",
                route="accept",
                route_reason=route_reason,
                completed_at=committed_at,
                now=committed_at,
            )

        if route_summary == "review":
            reviewed_at = utc_now()
            for route in routes:
                if route["route"] != "accept":
                    continue
                field = field_by_name[route["field_name"]]
                final_value = loads_json(field["agent_value_json"], None)
                extraction_crud.update_field_final_value(
                    self.connection,
                    task_id=task_id,
                    field_name=field["field_name"],
                    final_value=final_value,
                    source="agent",
                    now=reviewed_at,
                )
                if not self.audit_service.has_commit(
                    task_id=task_id,
                    field_name=field["field_name"],
                ):
                    self.audit_service.commit_field(
                        task_id=task_id,
                        field=field,
                        trace=trace_by_name.get(field["field_name"]),
                        route=route,
                        final_value=final_value,
                        reviewed=False,
                        review_decision=None,
                        review_value=None,
                        committed_by="agent",
                        committed_at=reviewed_at,
                    )
            return tasks_crud.update_task(
                self.connection,
                task_id=task_id,
                status="waiting_review",
                stage="review",
                route="review",
                route_reason=route_reason,
                now=reviewed_at,
            )

        rejected_at = utc_now()
        return tasks_crud.update_task(
            self.connection,
            task_id=task_id,
            status="rejected",
            stage="done",
            route="reject",
            route_reason=route_reason,
            completed_at=rejected_at,
            now=rejected_at,
        )

    def _infer_file_type(self, filename: str) -> str:
        suffix = Path(filename).suffix.lower().lstrip(".")
        if suffix not in self.settings.supported_file_types:
            raise ValidationError(f"unsupported file type: {suffix or 'unknown'}")
        return suffix

    def _resolve_task_spec(
        self,
        task_type: str,
        task_spec: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if task_spec is not None:
            return task_spec
        raise ValidationError("task_spec is required")

    def _normalize_blocks(
        self,
        *,
        document_id: str,
        raw_blocks: list[dict[str, Any]],
        markdown: str,
    ) -> list[dict[str, Any]]:
        source_blocks = raw_blocks or [{"text": markdown, "kind": "text"}]
        normalized: list[dict[str, Any]] = []
        for index, block in enumerate(source_blocks, start=1):
            page_no = block.get("page_no") or block.get("page")
            block_id = block.get("block_id") or f"{document_id}:p{page_no or 0}:b{index}"
            normalized.append(
                {
                    "document_id": block.get("document_id") or document_id,
                    "block_id": block_id,
                    "text": block.get("text") or "",
                    "page_no": page_no,
                    "bbox": block.get("bbox"),
                    "kind": block.get("kind") or "text",
                    "meta_info": block.get("meta_info") or {},
                }
            )
        return normalized

    def _summarize_routes(self, routes: list[dict[str, Any]]) -> str:
        route_names = {route["route"] for route in routes}
        if "reject" in route_names:
            return "reject"
        if "review" in route_names:
            return "review"
        return "accept"

    def _summarize_route_reason(self, routes: list[dict[str, Any]]) -> str | None:
        for expected_route in ("reject", "review", "accept"):
            for route in routes:
                if route["route"] == expected_route:
                    return route["route_reason"]
        return None

    def _serialize_result_field(
        self,
        field: dict[str, Any],
        route: dict[str, Any] | None,
        review_field: dict[str, Any] | None,
        committed: bool,
    ) -> dict[str, Any]:
        return {
            "field_name": field["field_name"],
            "display_name": field["display_name"],
            "agent_value": loads_json(field["agent_value_json"], None),
            "review_value": loads_json(review_field["review_value_json"], None)
            if review_field
            else None,
            "final_value": loads_json(field["final_value_json"], None),
            "field_status": field["agent_status"],
            "route": route["route"] if route else None,
            "source": field["source"],
            "committed": committed,
        }

    def _serialize_trace_field(self, trace: dict[str, Any]) -> dict[str, Any]:
        return {
            "field_name": trace["field_name"],
            "status": trace["trace_status"],
            "evidence": loads_json(trace["evidence_json"], {}),
            "related_fields": loads_json(trace["related_fields_json"], []),
            "actions": loads_json(trace["actions_json"], []),
            "reason": trace["reason"],
            "failure_reason": trace["failure_reason"],
        }
