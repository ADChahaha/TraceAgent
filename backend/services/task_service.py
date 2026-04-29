from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.core.config import BackendSettings
from backend.core.storage import compute_sha256
from backend.crud import agent_stage_runs as agent_stage_runs_crud
from backend.crud import audit as audit_crud
from backend.crud import extraction as extraction_crud
from backend.crud import reviews as reviews_crud
from backend.crud import tasks as tasks_crud
from backend.crud.json_utils import loads_json
from backend.services.agent_process import build_field_agent_process, serialize_field_agent_process
from backend.services.audit_service import AuditService
from backend.services.errors import AgentServiceError, NotFoundError, ValidationError
from backend.services.route_policy import build_route_policy_request
from backend.services.time_utils import utc_now


@dataclass(frozen=True)
class UploadedFilePayload:
    file_bytes: bytes
    filename: str
    content_type: str | None


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

    def upload_file_payload(
        self,
        *,
        file_bytes: bytes,
        filename: str,
        content_type: str | None,
    ) -> UploadedFilePayload:
        return UploadedFilePayload(
            file_bytes=file_bytes,
            filename=filename,
            content_type=content_type,
        )

    def create_task(
        self,
        *,
        files: list[UploadedFilePayload] | None = None,
        file_bytes: bytes | None = None,
        filename: str = "",
        content_type: str | None = None,
        task_type: str,
        task_spec: dict[str, Any] | None,
        metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
        upload_files = self._resolve_upload_files(
            files=files,
            file_bytes=file_bytes,
            filename=filename,
            content_type=content_type,
        )
        for upload_file in upload_files:
            self._infer_file_type(upload_file.filename)
        resolved_task_spec = self._resolve_task_spec(task_type, task_spec)
        metadata = metadata or {}
        now = utc_now()
        task_id = f"task_{uuid.uuid4().hex}"
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
                upload_files=upload_files,
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
        needs_review = task["status"] == "waiting_review"
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
        fields = {
            field["field_name"]: field
            for field in extraction_crud.list_extracted_fields(self.connection, task_id)
        }
        traces = extraction_crud.list_field_traces(self.connection, task_id)
        trace_payload = loads_json(agent_run["trace_json"], {}) if agent_run else {}
        routes = extraction_crud.list_field_routes(self.connection, task_id)
        documents = tasks_crud.list_documents_by_task(self.connection, task_id)
        agent_stage_runs = agent_stage_runs_crud.list_agent_stage_runs(
            self.connection,
            task_id,
        )
        return {
            "task_id": task["id"],
            "agent_status": agent_run["agent_status"] if agent_run else None,
            "failure_reason": agent_run["failure_reason"] if agent_run else None,
            "steps": self._serialize_trace_steps(
                task=task,
                documents=documents,
                agent_run=agent_run,
                trace_payload=trace_payload,
                routes=routes,
            ),
            "agent_trace": [
                self._serialize_agent_stage_run(stage_run)
                for stage_run in agent_stage_runs
            ],
            "fields": [
                self._serialize_trace_field(trace, fields.get(trace["field_name"]))
                for trace in traces
            ],
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

    def _save_agent_stage_run(
        self,
        *,
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
        return agent_stage_runs_crud.create_agent_stage_run(
            self.connection,
            run_id=f"stage_run_{uuid.uuid4().hex}",
            task_id=task_id,
            sequence=sequence,
            stage=stage,
            agent_name=agent_name,
            status=status,
            failure_reason=failure_reason,
            request=request,
            response=response,
            trace=trace,
            started_at=started_at,
            finished_at=finished_at,
        )

    def _run_agent_pipeline(
        self,
        *,
        task_id: str,
        upload_files: list[UploadedFilePayload],
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
        document_bundle = self._process_documents(
            task_id=task_id,
            upload_files=upload_files,
            sequence_start=1,
        )
        next_trace_sequence = document_bundle["next_trace_sequence"]

        extraction_started_at = utc_now()
        tasks_crud.update_task(
            self.connection,
            task_id=task_id,
            stage="extraction",
            now=extraction_started_at,
        )
        extraction_metadata = {
            **metadata,
            "task_id": task_id,
            "task_type": task_type,
            **document_bundle["metadata"],
        }
        extraction_request = {
            "blocks": document_bundle["blocks"],
            "markdown": document_bundle["markdown"],
            "md_list": document_bundle["md_list"],
            "task_spec": task_spec,
            "metadata": extraction_metadata,
            "run_options": None,
        }
        extraction_result = self.agent_client.extract_fields(
            blocks=document_bundle["blocks"],
            markdown=document_bundle["markdown"],
            md_list=document_bundle["md_list"],
            task_spec=task_spec,
            metadata=extraction_metadata,
            run_options=None,
        )
        extraction_finished_at = utc_now()
        self._save_agent_stage_run(
            task_id=task_id,
            sequence=next_trace_sequence,
            stage="extraction",
            agent_name="file_extraction_agent",
            status=extraction_result.get("status") or "completed",
            failure_reason=extraction_result.get("failure_reason"),
            request=extraction_request,
            response=extraction_result,
            trace=extraction_result.get("trace") or {},
            started_at=extraction_started_at,
            finished_at=extraction_finished_at,
        )
        next_trace_sequence += 1
        extraction_crud.create_agent_run(
            self.connection,
            run_id=f"run_{uuid.uuid4().hex}",
            task_id=task_id,
            agent_status=extraction_result.get("status") or "completed",
            failure_reason=extraction_result.get("failure_reason"),
            request={
                "task_spec": task_spec,
                "metadata": metadata,
                **document_bundle["metadata"],
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
                **document_bundle["metadata"],
            },
        )
        route_result = self.agent_client.evaluate_route_policy(**route_request)
        route_finished_at = utc_now()
        self._save_agent_stage_run(
            task_id=task_id,
            sequence=next_trace_sequence,
            stage="route_policy",
            agent_name="route_policy_agent",
            status=route_result.get("status") or "completed",
            failure_reason=route_result.get("failure_reason"),
            request=route_request,
            response=route_result,
            trace=route_result.get("trace") or {
                "field_routes": route_result.get("field_routes") or [],
                "warnings": route_result.get("warnings") or [],
                "metadata": route_result.get("metadata") or {},
            },
            started_at=route_started_at,
            finished_at=route_finished_at,
        )
        if route_result.get("status") == "failed":
            return tasks_crud.update_task(
                self.connection,
                task_id=task_id,
                status="failed",
                stage="done",
                error_message=route_result.get("failure_reason"),
                completed_at=route_finished_at,
                now=route_finished_at,
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

    def _process_documents(
        self,
        *,
        task_id: str,
        upload_files: list[UploadedFilePayload],
        sequence_start: int,
    ) -> dict[str, Any]:
        next_trace_sequence = sequence_start
        document_ids: list[str] = []
        all_blocks: list[dict[str, Any]] = []
        all_md_list: list[str] = []
        markdown_parts: list[str] = []

        for upload_file in upload_files:
            document_id = f"doc_{uuid.uuid4().hex}"
            file_type = self._infer_file_type(upload_file.filename)
            upload_sha256 = compute_sha256(upload_file.file_bytes)
            document_started_at = utc_now()
            document_request = {
                "document_id": document_id,
                "filename": upload_file.filename,
                "file_type": file_type,
                "content_type": upload_file.content_type,
                "upload_size_bytes": len(upload_file.file_bytes),
                "upload_sha256": upload_sha256,
            }
            document_result = self.agent_client.process_document(
                file_bytes=upload_file.file_bytes,
                filename=upload_file.filename,
                content_type=upload_file.content_type,
                file_type=file_type,
            )
            document_finished_at = utc_now()
            self._save_agent_stage_run(
                task_id=task_id,
                sequence=next_trace_sequence,
                stage="document_processing",
                agent_name="document_processor",
                status=document_result.get("status") or "completed",
                failure_reason=document_result.get("failure_reason"),
                request=document_request,
                response=document_result,
                trace=document_result.get("trace") or {
                    "meta_info": document_result.get("meta_info") or {},
                    "warnings": document_result.get("warnings") or [],
                },
                started_at=document_started_at,
                finished_at=document_finished_at,
            )
            next_trace_sequence += 1
            markdown = document_result.get("markdown") or ""
            md_list = document_result.get("md_list") or []
            blocks = self._normalize_blocks(
                document_id=document_id,
                raw_blocks=document_result.get("blocks") or [],
                markdown=markdown,
            )
            document_saved_at = utc_now()
            tasks_crud.create_document(
                self.connection,
                document_id=document_id,
                task_id=task_id,
                filename=upload_file.filename,
                file_type=file_type,
                content_type=upload_file.content_type,
                upload_size_bytes=len(upload_file.file_bytes),
                upload_sha256=upload_sha256,
                markdown=markdown,
                md_list=md_list,
                blocks=blocks,
                processor_meta=document_result.get("meta_info") or {},
                warnings=document_result.get("warnings") or [],
                now=document_saved_at,
            )
            document_ids.append(document_id)
            all_blocks.extend(blocks)
            all_md_list.extend(md_list)
            if markdown:
                markdown_parts.append(markdown)

        metadata = {"document_ids": document_ids}
        if document_ids:
            metadata["document_id"] = document_ids[0]
        return {
            "blocks": all_blocks,
            "markdown": "\n\n".join(markdown_parts),
            "md_list": all_md_list,
            "metadata": metadata,
            "next_trace_sequence": next_trace_sequence,
        }

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

    def _resolve_upload_files(
        self,
        *,
        files: list[UploadedFilePayload] | None,
        file_bytes: bytes | None,
        filename: str,
        content_type: str | None,
    ) -> list[UploadedFilePayload]:
        if files:
            return files
        if file_bytes is not None:
            return [
                UploadedFilePayload(
                    file_bytes=file_bytes,
                    filename=filename,
                    content_type=content_type,
                )
            ]
        raise ValidationError("at least one file is required")

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

    def _serialize_trace_field(
        self,
        trace: dict[str, Any],
        field: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        value = loads_json(field["agent_value_json"], None) if field else None
        serialized = serialize_field_agent_process(trace, value=value)
        assert serialized is not None
        return serialized

    def _serialize_agent_stage_run(self, stage_run: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": stage_run["id"],
            "sequence": stage_run["sequence"],
            "stage": stage_run["stage"],
            "agent": stage_run["agent_name"],
            "status": stage_run["status"],
            "failure_reason": stage_run["failure_reason"],
            "request": loads_json(stage_run["request_json"], {}),
            "response": loads_json(stage_run["response_json"], {}),
            "trace": loads_json(stage_run["trace_json"], {}),
            "started_at": stage_run["started_at"],
            "finished_at": stage_run["finished_at"],
        }

    def _serialize_trace_steps(
        self,
        *,
        task: dict[str, Any],
        documents: list[dict[str, Any]],
        agent_run: dict[str, Any] | None,
        trace_payload: dict[str, Any],
        routes: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        steps = [
            self._serialize_document_step(documents),
        ]
        if agent_run is not None:
            steps.append(
                self._serialize_extraction_step(
                    agent_run=agent_run,
                    trace_payload=trace_payload,
                )
            )
        if routes:
            steps.append(self._serialize_route_policy_step(routes))
        if task["status"] in {"completed", "waiting_review", "rejected", "failed"}:
            steps[-1]["is_terminal_step"] = task["stage"] == "done"
        return steps

    def _serialize_document_step(self, documents: list[dict[str, Any]]) -> dict[str, Any]:
        serialized_documents = []
        warning_count = 0
        block_count = 0
        for document in documents:
            blocks = loads_json(document["blocks_json"], [])
            warnings = loads_json(document["warnings_json"], [])
            block_count += len(blocks)
            warning_count += len(warnings)
            serialized_documents.append(
                {
                    "document_id": document["id"],
                    "filename": document["filename"],
                    "file_type": document["file_type"],
                    "content_type": document["content_type"],
                    "block_count": len(blocks),
                    "markdown_chars": len(document["markdown"]),
                    "warning_count": len(warnings),
                    "processed_at": document["processed_at"],
                }
            )
        return {
            "stage": "document_processing",
            "agent": "document_processor",
            "status": "completed" if documents else "pending",
            "started_at": documents[0]["created_at"] if documents else None,
            "finished_at": documents[-1]["processed_at"] if documents else None,
            "summary": {
                "document_count": len(documents),
                "block_count": block_count,
                "warning_count": warning_count,
            },
            "documents": serialized_documents,
        }

    def _serialize_extraction_step(
        self,
        *,
        agent_run: dict[str, Any],
        trace_payload: dict[str, Any],
    ) -> dict[str, Any]:
        result_payload = loads_json(agent_run["result_json"], {})
        fields = (result_payload.get("fields") or []) if isinstance(result_payload, dict) else []
        warnings = trace_payload.get("warnings") or []
        return {
            "stage": "extraction",
            "agent": "file_extraction_agent",
            "status": agent_run["agent_status"],
            "started_at": agent_run["started_at"],
            "finished_at": agent_run["finished_at"],
            "failure_reason": agent_run["failure_reason"],
            "summary": {
                "field_count": len(fields),
                "warning_count": len(warnings),
                "resolved_count": sum(1 for field in fields if field.get("status") == "resolved"),
                "failed_count": sum(1 for field in fields if field.get("status") == "failed"),
            },
            "field_decisions": self._serialize_extraction_field_decisions(
                trace_payload=trace_payload,
                result_payload=result_payload,
            ),
            "warnings": warnings,
            "metadata": trace_payload.get("metadata", {}),
        }

    def _serialize_extraction_field_decisions(
        self,
        *,
        trace_payload: dict[str, Any],
        result_payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        result_fields = (
            result_payload.get("fields") or []
            if isinstance(result_payload, dict)
            else []
        )
        result_by_name = {
            field.get("field_name"): field
            for field in result_fields
            if isinstance(field, dict)
        }
        decisions = []
        for trace in trace_payload.get("fields") or []:
            if not isinstance(trace, dict):
                continue
            field_name = trace.get("field_name")
            result_field = result_by_name.get(field_name) or {}
            decision = build_field_agent_process(
                field_name=field_name,
                status=trace.get("status") or result_field.get("status"),
                value=result_field.get("value"),
                evidence=trace.get("evidence") or {},
                related_fields=trace.get("related_fields") or [],
                actions=trace.get("actions") or [],
                reason=trace.get("reason"),
                failure_reason=trace.get("failure_reason"),
            )
            decisions.append(decision)
        return decisions

    def _serialize_route_policy_step(self, routes: list[dict[str, Any]]) -> dict[str, Any]:
        route_counts = {"accept": 0, "review": 0, "reject": 0}
        serialized_routes = []
        for route in routes:
            route_name = route["route"]
            if route_name in route_counts:
                route_counts[route_name] += 1
            serialized_routes.append(
                {
                    "field_name": route["field_name"],
                    "route": route_name,
                    "needs_review": bool(route["needs_review"]),
                    "route_reason": route["route_reason"],
                }
            )
        return {
            "stage": "route_policy",
            "agent": "route_policy_agent",
            "status": "completed",
            "started_at": routes[0]["created_at"],
            "finished_at": routes[-1]["created_at"],
            "summary": {
                "field_count": len(routes),
                "routes": route_counts,
            },
            "routes": serialized_routes,
        }
