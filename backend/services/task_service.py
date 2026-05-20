from __future__ import annotations

import re
import sqlite3
import uuid
from dataclasses import dataclass
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from backend.core.config import BackendSettings
from backend.core.storage import compute_sha256
from backend.crud import agent_stage_runs as agent_stage_runs_crud
from backend.crud import audit as audit_crud
from backend.crud import extraction as extraction_crud
from backend.crud import task_events as task_events_crud
from backend.crud import tasks as tasks_crud
from backend.crud.json_utils import loads_json
from backend.services.agent_process import (
    build_document_block_lookup,
    build_field_agent_process,
    serialize_field_agent_process,
)
from backend.services.audit_service import AuditService
from backend.services.errors import AgentServiceError, NotFoundError, ValidationError
from backend.services.time_utils import utc_now


@dataclass(frozen=True)
class UploadedFilePayload:
    file_bytes: bytes
    filename: str
    content_type: str | None


class _ReplayDisplayHtmlSanitizer(HTMLParser):
    def __init__(self, source_id_replacements: dict[str, str] | None = None):
        super().__init__(convert_charrefs=False)
        self.parts: list[str] = []
        self.skip_depth = 0
        self.source_id_replacements = source_id_replacements or {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.skip_depth > 0:
            self.skip_depth += 1
            return
        if _is_replay_chrome_attrs(attrs):
            self.skip_depth = 1
            return
        replaced_attrs, changed = _replace_replay_source_attrs(attrs, self.source_id_replacements)
        self.parts.append(_format_start_tag(tag, replaced_attrs) if changed else self.get_starttag_text() or _format_start_tag(tag, attrs))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.skip_depth > 0 or _is_replay_chrome_attrs(attrs):
            return
        replaced_attrs, changed = _replace_replay_source_attrs(attrs, self.source_id_replacements)
        self.parts.append(
            _format_start_tag(tag, replaced_attrs, self_closing=True)
            if changed
            else self.get_starttag_text() or _format_start_tag(tag, attrs, self_closing=True)
        )

    def handle_endtag(self, tag: str) -> None:
        if self.skip_depth > 0:
            self.skip_depth -= 1
            return
        self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if self.skip_depth == 0:
            self.parts.append(data)

    def handle_entityref(self, name: str) -> None:
        if self.skip_depth == 0:
            self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self.skip_depth == 0:
            self.parts.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        if self.skip_depth == 0:
            self.parts.append(f"<!--{data}-->")

    def handle_decl(self, decl: str) -> None:
        if self.skip_depth == 0:
            self.parts.append(f"<!{decl}>")

    def handle_pi(self, data: str) -> None:
        if self.skip_depth == 0:
            self.parts.append(f"<?{data}>")

    def get_html(self) -> str:
        return "".join(self.parts)


def sanitize_replay_display_html(display_html: str, source_id_replacements: dict[str, str] | None = None) -> str:
    parser = _ReplayDisplayHtmlSanitizer(source_id_replacements=source_id_replacements)
    parser.feed(display_html)
    parser.close()
    return _sanitize_replay_display_css(parser.get_html())


def _is_replay_chrome_attrs(attrs: list[tuple[str, str | None]]) -> bool:
    attr_map = {name.lower(): value or "" for name, value in attrs}
    data_type = attr_map.get("data-type", "").lower()
    class_names = attr_map.get("class", "").lower().split()
    element_id = attr_map.get("id", "")
    text_type = data_type.replace("-", "_")
    if text_type in {"page_number", "page_header", "page_footer"}:
        return True
    if {"page-number", "block-page_footer", "block-page_header"} & set(class_names):
        return True
    return bool(re.search(r"_b\d+$", element_id) and text_type in {"page_number", "page_header", "page_footer"})


def _format_start_tag(tag: str, attrs: list[tuple[str, str | None]], *, self_closing: bool = False) -> str:
    attr_text = "".join(
        f" {name}" if value is None else f' {name}="{escape(value, quote=True)}"'
        for name, value in attrs
    )
    closing = " /" if self_closing else ""
    return f"<{tag}{attr_text}{closing}>"


def _replace_replay_source_attrs(
    attrs: list[tuple[str, str | None]],
    source_id_replacements: dict[str, str],
) -> tuple[list[tuple[str, str | None]], bool]:
    if not source_id_replacements:
        return attrs, False
    changed = False
    next_attrs: list[tuple[str, str | None]] = []
    replacement_for_element = ""
    has_data_element_id = False
    for name, value in attrs:
        lower_name = name.lower()
        if lower_name == "data-element-id":
            has_data_element_id = True
        replacement = source_id_replacements.get(value or "") if lower_name in {"id", "data-element-id"} else None
        if replacement:
            next_attrs.append((name, replacement))
            replacement_for_element = replacement
            changed = True
            continue
        next_attrs.append((name, value))
    if replacement_for_element and not has_data_element_id:
        next_attrs.append(("data-element-id", replacement_for_element))
        changed = True
    return next_attrs, changed


def _sanitize_replay_display_css(html: str) -> str:
    output: list[str] = []
    cursor = 0
    lower_html = html.lower()
    while True:
        style_start = lower_html.find("<style", cursor)
        if style_start == -1:
            output.append(html[cursor:])
            break
        style_open_end = lower_html.find(">", style_start)
        if style_open_end == -1:
            output.append(html[cursor:])
            break
        style_close = lower_html.find("</style>", style_open_end + 1)
        if style_close == -1:
            output.append(html[cursor:])
            break

        output.append(html[cursor:style_open_end + 1])
        output.append(_sanitize_replay_css_rules(html[style_open_end + 1:style_close]))
        output.append(html[style_close:style_close + len("</style>")])
        cursor = style_close + len("</style>")
    return "".join(output)


def _sanitize_replay_css_rules(css: str) -> str:
    output: list[str] = []
    cursor = 0
    css_length = len(css)
    while cursor < css_length:
        open_brace = css.find("{", cursor)
        if open_brace == -1:
            output.append(css[cursor:])
            break
        close_brace = css.find("}", open_brace + 1)
        if close_brace == -1:
            output.append(css[cursor:])
            break

        selector_start = cursor
        selector = css[selector_start:open_brace]
        if _is_replay_chrome_css_selector(selector):
            output.append(css[cursor:selector_start])
        else:
            output.append(css[cursor:close_brace + 1])
        cursor = close_brace + 1
    return "".join(output)


def _is_replay_chrome_css_selector(selector: str) -> bool:
    normalized = selector.lower()
    return any(
        class_name in normalized
        for class_name in (".page-number", ".block-page_footer", ".block-page_header")
    )


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
        run_pipeline: bool = True,
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
        task = tasks_crud.create_task(
            self.connection,
            task_id=task_id,
            task_type=task_type,
            metadata=metadata,
            now=now,
        )
        self._emit_task_event(
            task,
            event_type="task.created",
            payload={"task_type": task_type},
            now=now,
        )

        if not run_pipeline:
            return self.serialize_created_task(task)

        return self.run_created_task(
            task_id=task_id,
            upload_files=upload_files,
            task_type=task_type,
            task_spec=resolved_task_spec,
            metadata=metadata,
            raise_on_error=True,
        )

    def run_created_task(
        self,
        *,
        task_id: str,
        upload_files: list[UploadedFilePayload],
        task_type: str,
        task_spec: dict[str, Any],
        metadata: dict[str, Any],
        raise_on_error: bool = False,
    ) -> dict[str, Any]:
        try:
            task = self._run_agent_pipeline(
                task_id=task_id,
                upload_files=upload_files,
                task_type=task_type,
                task_spec=task_spec,
                metadata=metadata,
            )
        except Exception as exc:
            failed_at = utc_now()
            failed_task = tasks_crud.update_task(
                self.connection,
                task_id=task_id,
                status="failed",
                stage="done",
                error_message=str(exc),
                completed_at=failed_at,
                now=failed_at,
            )
            self._emit_task_event(
                failed_task,
                event_type="task.failed",
                payload={"error_message": str(exc)},
                now=failed_at,
            )
            if raise_on_error:
                if isinstance(exc, (ValidationError, AgentServiceError)):
                    raise
                raise AgentServiceError(str(exc)) from exc
            task = self.get_task_or_raise(task_id)

        return self.serialize_created_task(task)

    def get_task_summary(self, task_id: str) -> dict[str, Any]:
        task = self.get_task_or_raise(task_id)
        return self._serialize_task_summary(task)

    def list_task_summaries(self, *, limit: int = 20) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(limit, 100))
        return [
            self._serialize_task_summary(task)
            for task in tasks_crud.list_tasks(self.connection, limit=bounded_limit)
        ]

    def _serialize_task_summary(self, task: dict[str, Any]) -> dict[str, Any]:
        task_id = task["id"]
        fields = extraction_crud.list_extracted_fields(self.connection, task_id)
        traces = extraction_crud.list_field_traces(self.connection, task_id)
        return {
            "task_id": task_id,
            "status": task["status"],
            "stage": task["stage"],
            "error_message": task["error_message"],
            "has_result": bool(fields),
            "has_trace": bool(traces),
            "stream": self._serialize_stream_state(task),
            "created_at": task["created_at"],
            "updated_at": task["updated_at"],
        }

    def get_result(self, task_id: str) -> dict[str, Any]:
        task = self.get_task_or_raise(task_id)
        fields = extraction_crud.list_extracted_fields(self.connection, task_id)
        committed_fields = {
            commit["field_name"]
            for commit in audit_crud.list_field_commits(self.connection, task_id)
        }
        return {
            "task_id": task["id"],
            "status": task["status"],
            "fields": [
                self._serialize_result_field(
                    field,
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
        documents = tasks_crud.list_documents_by_task(self.connection, task_id)
        block_lookup = build_document_block_lookup(documents)
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
                block_lookup=block_lookup,
            ),
            "agent_trace": [
                self._serialize_agent_stage_run(stage_run)
                for stage_run in agent_stage_runs
            ],
            "fields": [
                self._serialize_trace_field(
                    trace,
                    fields.get(trace["field_name"]),
                    block_lookup=block_lookup,
                )
                for trace in traces
            ],
            "metadata": trace_payload.get("metadata", {}),
        }

    def get_replay(self, task_id: str) -> dict[str, Any]:
        task = self.get_task_or_raise(task_id)
        agent_run = extraction_crud.get_latest_agent_run(self.connection, task_id)
        trace_payload = loads_json(agent_run["trace_json"], {}) if agent_run else {}
        result_payload = loads_json(agent_run["result_json"], {}) if agent_run else {}
        documents = tasks_crud.list_documents_by_task(self.connection, task_id)
        agent_stage_runs = agent_stage_runs_crud.list_agent_stage_runs(
            self.connection,
            task_id,
        )
        live_source_index = self._latest_live_source_index(task_id)
        raw_source_selectors = trace_payload.get("source_selectors") or live_source_index.get("source_selectors") or {}
        source_selectors = {
            path_id: path_id
            for path_id, source_id in raw_source_selectors.items()
            if isinstance(path_id, str) and isinstance(source_id, str) and path_id and source_id
        } if isinstance(raw_source_selectors, dict) else {}
        return {
            "task_id": task["id"],
            "status": task["status"],
            "stage": task["stage"],
            "documents": [
                {
                    "document_id": document["id"],
                    "filename": document["filename"],
                }
                for document in documents
            ],
            "display_html": self._build_replay_display_html(agent_stage_runs, source_selectors=raw_source_selectors),
            "outline_tree": trace_payload.get("document_tree") or live_source_index.get("document_tree") or [],
            "source_selectors": source_selectors,
            "broad_plan": trace_payload.get("broad_plan"),
            "actions": self._serialize_replay_actions(trace_payload),
            "result": result_payload,
            "field_states": trace_payload.get("field_states") or {},
            "audit": {},
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
            "error_message": task["error_message"],
            "stream": self._serialize_stream_state(task),
        }

    def list_task_events(self, task_id: str, *, after_sequence: int = 0) -> list[dict[str, Any]]:
        self.get_task_or_raise(task_id)
        return [
            self._serialize_task_event(event)
            for event in task_events_crud.list_task_events(
                self.connection,
                task_id=task_id,
                after_sequence=max(0, after_sequence),
            )
        ]

    def _serialize_stream_state(self, task: dict[str, Any]) -> dict[str, Any]:
        state = "ended" if task["status"] in {"completed", "failed"} else "running"
        return {
            "state": state,
            "last_event_seq": task_events_crud.get_last_sequence(self.connection, task["id"]),
        }

    def _serialize_task_event(self, event: dict[str, Any]) -> dict[str, Any]:
        return {
            "seq": event["sequence"],
            "task_id": event["task_id"],
            "type": event["event_type"],
            "status": event["status"],
            "stage": event["stage"],
            "payload": loads_json(event["payload_json"], {}),
            "created_at": event["created_at"],
        }

    def _serialize_replay_actions(self, trace_payload: Any) -> list[Any]:
        if isinstance(trace_payload, dict):
            event_actions = self._serialize_replay_actions_from_events(trace_payload.get("events"))
            if event_actions:
                return event_actions
            actions = trace_payload.get("actions")
        else:
            actions = trace_payload
        if not isinstance(actions, list):
            return []
        serialized: list[Any] = []
        for action in actions:
            if isinstance(action, dict):
                serialized.append({key: value for key, value in action.items() if key != "reason"})
            else:
                serialized.append(action)
        return serialized

    def _serialize_replay_actions_from_events(self, events: Any) -> list[dict[str, Any]]:
        if not isinstance(events, list):
            return []
        serialized: list[dict[str, Any]] = []
        for event in events:
            if not isinstance(event, dict):
                continue
            event_type = event.get("type")
            if event_type == "model_message":
                content = str(event.get("content") or "").strip()
                if not content:
                    continue
                action = {
                    "tool_name": "model_message",
                    "reason": content,
                    "result": {"ok": True},
                    "metadata": {
                        "seq": event.get("seq"),
                        "event_type": event_type,
                    },
                }
                serialized.append(self._drop_empty_metadata(action))
                continue
            if event_type not in {"tool_completed", "tool_failed"}:
                continue
            tool_name = event.get("tool") or event.get("tool_name")
            if not isinstance(tool_name, str) or not tool_name:
                continue
            action = {
                "tool_name": tool_name,
                "args": event.get("args"),
                "result": event.get("result"),
                "metadata": {
                    "seq": event.get("seq"),
                    "event_type": event_type,
                },
            }
            serialized.append(self._drop_empty_metadata({key: value for key, value in action.items() if value is not None}))
        return serialized

    def _drop_empty_metadata(self, action: dict[str, Any]) -> dict[str, Any]:
        metadata = action.get("metadata")
        if not isinstance(metadata, dict):
            return action
        clean_metadata = {key: value for key, value in metadata.items() if value is not None}
        if clean_metadata:
            return {**action, "metadata": clean_metadata}
        return {key: value for key, value in action.items() if key != "metadata"}

    def _latest_live_source_index(self, task_id: str) -> dict[str, Any]:
        source_index: dict[str, Any] = {}
        for event in task_events_crud.list_task_events(
            self.connection,
            task_id=task_id,
            after_sequence=0,
        ):
            if event["event_type"] != "agent.event":
                continue
            payload = loads_json(event["payload_json"], {})
            if payload.get("type") != "source_indexed":
                continue
            result = payload.get("result")
            if isinstance(result, dict):
                source_index = result
        return source_index

    def _emit_task_event(
        self,
        task: dict[str, Any],
        *,
        event_type: str,
        payload: dict[str, Any] | None = None,
        now: str | None = None,
    ) -> dict[str, Any]:
        return task_events_crud.create_task_event(
            self.connection,
            event_id=f"event_{uuid.uuid4().hex}",
            task_id=task["id"],
            event_type=event_type,
            status=task["status"],
            stage=task["stage"],
            payload=payload or {},
            created_at=now or utc_now(),
        )

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
        task = tasks_crud.update_task(
            self.connection,
            task_id=task_id,
            status="processing",
            stage="document_processing",
            now=now,
        )
        self._emit_task_event(
            task,
            event_type="task.stage_changed",
            payload={"stage": "document_processing"},
            now=now,
        )
        document_bundle = self._process_documents(
            task_id=task_id,
            upload_files=upload_files,
            sequence_start=1,
        )
        next_trace_sequence = document_bundle["next_trace_sequence"]

        extraction_started_at = utc_now()
        task = tasks_crud.update_task(
            self.connection,
            task_id=task_id,
            stage="extraction",
            now=extraction_started_at,
        )
        self._emit_task_event(
            task,
            event_type="task.stage_changed",
            payload={"stage": "extraction"},
            now=extraction_started_at,
        )
        extraction_metadata = {
            **metadata,
            "task_id": task_id,
            "task_type": task_type,
            **document_bundle["metadata"],
        }
        extraction_request = {
            "html_chars": len(document_bundle["html"]),
            "task_spec": task_spec,
            "metadata": extraction_metadata,
            "run_options": None,
        }
        extraction_result = self._extract_fields_with_agent_events(
            task_id=task_id,
            html=document_bundle["html"],
            task_spec=task_spec,
            run_options=None,
        )
        extraction_finished_at = utc_now()
        self._emit_task_event(
            self.get_task_or_raise(task_id),
            event_type="agent.event",
            payload={
                "agent": "file_extraction_agent",
                "type": "result_completed",
                "status": extraction_result.get("status") or "completed",
            },
            now=extraction_finished_at,
        )
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
            failed_task = tasks_crud.update_task(
                self.connection,
                task_id=task_id,
                status="failed",
                stage="done",
                error_message=extraction_result.get("failure_reason"),
                completed_at=extraction_finished_at,
                now=extraction_finished_at,
            )
            self._emit_task_event(
                failed_task,
                event_type="task.failed",
                payload={"error_message": extraction_result.get("failure_reason")},
                now=extraction_finished_at,
            )
            return failed_task

        self._save_extraction_result(
            task_id=task_id,
            task_spec=task_spec,
            extraction_result=extraction_result,
            now=extraction_finished_at,
        )
        fields = extraction_crud.list_extracted_fields(self.connection, task_id)
        traces = extraction_crud.list_field_traces(self.connection, task_id)
        return self._commit_extraction_outcome(
            task_id=task_id,
            fields=fields,
            traces=traces,
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
        html_parts: list[str] = []

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
            self._emit_task_event(
                self.get_task_or_raise(task_id),
                event_type="document.processed",
                payload={
                    "document_id": document_id,
                    "filename": upload_file.filename,
                    "file_type": file_type,
                    "status": document_result.get("status") or "completed",
                    "warning_count": len(document_result.get("warnings") or []),
                },
                now=document_finished_at,
            )
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
            html = document_result.get("html") or document_result.get("display_html") or ""
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
            if html:
                html_parts.append(html)

        metadata = {"document_ids": document_ids}
        if document_ids:
            metadata["document_id"] = document_ids[0]
        html = "\n\n".join(html_parts).strip()
        if not html:
            html = "\n\n".join(f'<p id="backend-fallback-p-{index}">{block.get("text", "")}</p>' for index, block in enumerate(all_blocks, start=1))
        return {
            "blocks": all_blocks,
            "markdown": "\n\n".join(markdown_parts),
            "md_list": all_md_list,
            "html": html,
            "metadata": metadata,
            "next_trace_sequence": next_trace_sequence,
        }

    def _extract_fields_with_agent_events(
        self,
        *,
        task_id: str,
        html: str,
        task_spec: dict[str, Any],
        run_options: dict[str, Any] | None,
    ) -> dict[str, Any]:
        extract_stream = getattr(self.agent_client, "extract_fields_stream", None)
        if not callable(extract_stream):
            return self.agent_client.extract_fields(
                html=html,
                task_spec=task_spec,
                run_options=run_options,
            )

        result_completed: dict[str, Any] | None = None
        for event in extract_stream(
            html=html,
            task_spec=task_spec,
            run_options=run_options,
        ):
            if not isinstance(event, dict):
                continue
            self._emit_agent_stream_event(task_id=task_id, event=event)
            if event.get("type") == "result_completed":
                result_completed = event

        if result_completed is None:
            raise AgentServiceError("file_extraction_agent stream ended without result_completed")
        return self._extract_result_from_stream_event(result_completed)

    def _emit_agent_stream_event(self, *, task_id: str, event: dict[str, Any]) -> None:
        event_type = str(event.get("type") or "agent.event")
        if event_type == "result_completed":
            return
        payload = {
            "agent": "file_extraction_agent",
            "type": event_type,
            "tool": event.get("tool") or event.get("tool_name"),
            "content": event.get("content"),
            "args": event.get("args"),
            "result": event.get("result"),
        }
        self._emit_task_event(
            self.get_task_or_raise(task_id),
            event_type="agent.event",
            payload={key: value for key, value in payload.items() if value is not None},
            now=utc_now(),
        )

    def _extract_result_from_stream_event(self, event: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": event.get("status") or "completed",
            "failure_reason": event.get("failure_reason"),
            "result": event.get("result") or {},
            "trace": event.get("trace") or {},
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
            (field.get("name") or field.get("field_name")): field
            for field in task_spec.get("fields", [])
        }
        normalized_fields = self._iter_extraction_result_fields(
            extraction_result,
            task_spec=task_spec,
        )
        trace_payload = extraction_result.get("trace") or {}
        trace_by_field = self._build_trace_by_field(trace_payload)
        for field in normalized_fields:
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
            self._emit_task_event(
                self.get_task_or_raise(task_id),
                event_type="field.written",
                payload={
                    "field_name": field_name,
                    "status": field.get("status") or "failed",
                    "value": field.get("value"),
                },
                now=now,
            )

    def _iter_extraction_result_fields(
        self,
        extraction_result: dict[str, Any],
        *,
        task_spec: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        result = extraction_result.get("result") or {}
        expected_fields = self._expected_task_fields(task_spec or {})
        if isinstance(result, dict) and isinstance(result.get("fields"), list):
            fields = self._normalize_result_fields(result["fields"])
            return self._append_missing_expected_fields(fields, expected_fields)
        if not isinstance(result, dict):
            return self._append_missing_expected_fields([], expected_fields)
        field_states = (extraction_result.get("trace") or {}).get("field_states") or {}
        fields = []
        for field_name, value in result.items():
            state = field_states.get(field_name) if isinstance(field_states, dict) else {}
            fields.append(
                {
                    "field_name": field_name,
                    "status": state.get("status") or "resolved",
                    "value": value,
                    "failure_reason": state.get("failure_reason"),
                }
            )
        return self._append_missing_expected_fields(fields, expected_fields)

    def _expected_task_fields(self, task_spec: dict[str, Any]) -> list[dict[str, Any]]:
        fields = task_spec.get("fields")
        if not isinstance(fields, list):
            return []
        expected = []
        seen: set[str] = set()
        for field in fields:
            if not isinstance(field, dict):
                continue
            field_name = field.get("name") or field.get("field_name")
            if not isinstance(field_name, str) or not field_name or field_name in seen:
                continue
            seen.add(field_name)
            expected.append(field)
        return expected

    def _append_missing_expected_fields(
        self,
        fields: list[dict[str, Any]],
        expected_fields: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        existing_names = {
            field.get("field_name")
            for field in fields
            if isinstance(field.get("field_name"), str)
        }
        next_fields = list(fields)
        for field_spec in expected_fields:
            field_name = field_spec.get("name") or field_spec.get("field_name")
            if field_name in existing_names:
                continue
            next_fields.append(
                {
                    "field_name": field_name,
                    "status": "failed",
                    "value": None,
                    "failure_reason": "file_extraction_agent did not return this field",
                }
            )
        return next_fields

    def _normalize_result_fields(self, fields: list[Any]) -> list[dict[str, Any]]:
        normalized_fields: list[dict[str, Any]] = []
        for index, field in enumerate(fields):
            if not isinstance(field, dict):
                raise ValueError(f"file_extraction_agent result.fields[{index}] must be an object")
            field_name = field.get("field_name")
            if not isinstance(field_name, str) or not field_name:
                raise ValueError(f"file_extraction_agent result.fields[{index}] missing field_name")
            normalized_fields.append(field)
        return normalized_fields

    def _build_trace_by_field(self, trace_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
        traces = trace_payload.get("fields")
        if isinstance(traces, list):
            trace_by_field: dict[str, dict[str, Any]] = {}
            for index, trace in enumerate(traces):
                if not isinstance(trace, dict):
                    raise ValueError(f"file_extraction_agent trace.fields[{index}] must be an object")
                field_name = trace.get("field_name")
                if not isinstance(field_name, str) or not field_name:
                    raise ValueError(f"file_extraction_agent trace.fields[{index}] missing field_name")
                trace_by_field[field_name] = trace
            return trace_by_field
        field_states = trace_payload.get("field_states") or {}
        actions = trace_payload.get("actions") or []
        trace_by_field: dict[str, dict[str, Any]] = {}
        if not isinstance(field_states, dict):
            return trace_by_field
        for field_name, state in field_states.items():
            if not isinstance(state, dict):
                continue
            evidence_ids = state.get("evidence_ids") or []
            trace_by_field[str(field_name)] = {
                "field_name": field_name,
                "status": state.get("status"),
                "evidence": {
                    "block_ids": evidence_ids,
                    "refs": [{"block_id": evidence_id} for evidence_id in evidence_ids],
                    "texts": [],
                    "status": state.get("status"),
                },
                "related_fields": [],
                "actions": [
                    action
                    for action in self._actions_for_field_from_flat_trace(
                        actions=actions,
                        field_name=str(field_name),
                    )
                ],
                "reason": None,
                "failure_reason": state.get("failure_reason"),
            }
        return trace_by_field

    def _actions_for_field_from_flat_trace(
        self,
        *,
        actions: list[Any],
        field_name: str,
    ) -> list[dict[str, Any]]:
        matched: list[dict[str, Any]] = []
        for action in actions:
            if not isinstance(action, dict):
                continue
            matched.append(action)
            if (
                action.get("tool_name") == "set_field"
                and (action.get("args") or {}).get("name") == field_name
            ):
                return matched
        return []

    def _commit_extraction_outcome(
        self,
        *,
        task_id: str,
        fields: list[dict[str, Any]],
        traces: list[dict[str, Any]],
    ) -> dict[str, Any]:
        trace_by_name = {trace["field_name"]: trace for trace in traces}
        committed_at = utc_now()
        for field in fields:
            if field["agent_status"] != "resolved":
                continue
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
                final_value=final_value,
                committed_by="agent",
                committed_at=committed_at,
            )
        completed_task = tasks_crud.update_task(
            self.connection,
            task_id=task_id,
            status="completed",
            stage="done",
            completed_at=committed_at,
            now=committed_at,
        )
        self._emit_task_event(
            completed_task,
            event_type="task.completed",
            payload={},
            now=committed_at,
        )
        return completed_task

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

    def _serialize_result_field(
        self,
        field: dict[str, Any],
        committed: bool,
    ) -> dict[str, Any]:
        return {
            "field_name": field["field_name"],
            "display_name": field["display_name"],
            "agent_value": loads_json(field["agent_value_json"], None),
            "final_value": loads_json(field["final_value_json"], None),
            "field_status": field["agent_status"],
            "source": field["source"],
            "committed": committed,
        }

    def _serialize_trace_field(
        self,
        trace: dict[str, Any],
        field: dict[str, Any] | None = None,
        *,
        block_lookup: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        value = loads_json(field["agent_value_json"], None) if field else None
        serialized = serialize_field_agent_process(
            trace,
            value=value,
            block_lookup=block_lookup,
        )
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

    def _build_replay_display_html(
        self,
        stage_runs: list[dict[str, Any]],
        *,
        source_selectors: dict[str, Any] | None = None,
    ) -> str:
        source_id_replacements = {
            source_id: path_id
            for path_id, source_id in (source_selectors or {}).items()
            if isinstance(path_id, str) and isinstance(source_id, str) and path_id and source_id
        }
        html_parts: list[str] = []
        for stage_run in stage_runs:
            if stage_run["agent_name"] != "document_processor":
                continue
            response = loads_json(stage_run["response_json"], {})
            display_html = response.get("display_html") or response.get("html")
            if isinstance(display_html, str) and display_html.strip():
                html_parts.append(sanitize_replay_display_html(display_html, source_id_replacements=source_id_replacements))
        return "\n\n".join(html_parts)

    def _serialize_trace_steps(
        self,
        *,
        task: dict[str, Any],
        documents: list[dict[str, Any]],
        agent_run: dict[str, Any] | None,
        trace_payload: dict[str, Any],
        block_lookup: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        steps = [
            self._serialize_document_step(documents),
        ]
        if agent_run is not None:
            steps.append(
                self._serialize_extraction_step(
                    agent_run=agent_run,
                    trace_payload=trace_payload,
                    block_lookup=block_lookup,
                )
            )
        if task["status"] in {"completed", "failed"}:
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
        block_lookup: dict[str, dict[str, Any]],
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
                block_lookup=block_lookup,
            ),
            "warnings": warnings,
            "metadata": trace_payload.get("metadata", {}),
        }

    def _serialize_extraction_field_decisions(
        self,
        *,
        trace_payload: dict[str, Any],
        result_payload: dict[str, Any],
        block_lookup: dict[str, dict[str, Any]],
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
                block_lookup=block_lookup,
            )
            decisions.append(decision)
        return decisions
