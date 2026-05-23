from __future__ import annotations

import json
import hashlib
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.core.config import BackendSettings
from backend.core.storage import compute_sha256
from backend.crud import qa_tasks as qa_crud
from backend.crud.json_utils import loads_json
from backend.services.errors import AgentServiceError, ConflictError, NotFoundError, ValidationError
from backend.services.time_utils import utc_now


DEFAULT_MEMORY = {
    "reading_history": [],
    "evidence_notes": [],
    "prior_answers": [],
    "open_threads": [],
}


@dataclass(frozen=True)
class UploadedFilePayload:
    file_bytes: bytes
    filename: str
    content_type: str | None


class QaTaskService:
    def __init__(
        self,
        *,
        connection: Any,
        settings: BackendSettings,
        agent_client,
    ):
        self._connection = connection
        self.settings = settings
        self.agent_client = agent_client

    @property
    def connection(self) -> sqlite3.Connection:
        connect = getattr(self._connection, "connect", None)
        if callable(connect):
            return connect()
        return self._connection

    def upload_file_payload(
        self,
        *,
        file_bytes: bytes,
        filename: str,
        content_type: str | None,
    ) -> UploadedFilePayload:
        return UploadedFilePayload(file_bytes=file_bytes, filename=filename, content_type=content_type)

    def create_task(
        self,
        *,
        files: list[UploadedFilePayload],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not files:
            raise ValidationError("at least one file is required")
        metadata = metadata or {}
        for upload_file in files:
            self._infer_file_type(upload_file.filename)
        now = utc_now()
        task_id = f"qa_task_{uuid.uuid4().hex}"
        task = qa_crud.create_task(
            self.connection,
            task_id=task_id,
            metadata=metadata,
            memory=dict(DEFAULT_MEMORY),
            now=now,
        )
        self._emit_event(task, event_type="task.created", payload={"metadata": metadata}, now=now)
        initial_snapshot = self.serialize_task(task)
        self._start_background_worker(
            name=f"qa-docs-{task_id}",
            target=self._process_task_documents,
            task_id=task_id,
            files=files,
        )
        return initial_snapshot

    def _process_task_documents(self, *, task_id: str, files: list[UploadedFilePayload]) -> None:
        try:
            for upload_file in files:
                self._process_document(task_id=task_id, upload_file=upload_file)
            ready_at = utc_now()
            active_turn = qa_crud.get_active_turn(self.connection, task_id)
            task = qa_crud.update_task(
                self.connection,
                task_id=task_id,
                status="running" if active_turn else "ready",
                stage="answering" if active_turn else "ready",
                now=ready_at,
            )
            self._emit_event(task, event_type="task.ready", payload={}, now=ready_at)
        except Exception as exc:
            failed_at = utc_now()
            task = qa_crud.update_task(
                self.connection,
                task_id=task_id,
                status="failed",
                stage="done",
                error_message=str(exc),
                now=failed_at,
            )
            self._emit_event(task, event_type="task.failed", payload={"error_message": str(exc)}, now=failed_at)
            active_turn = qa_crud.get_active_turn(self.connection, task_id)
            if active_turn is not None:
                qa_crud.update_turn(
                    self.connection,
                    turn_id=active_turn["id"],
                    status="failed",
                    error_message=str(exc),
                    completed_at=failed_at,
                    now=failed_at,
                )
                self._emit_event(
                    task,
                    turn_id=active_turn["id"],
                    event_type="turn.failed",
                    payload={"turn_id": active_turn["id"], "error_message": str(exc)},
                    now=failed_at,
                )

    def create_input(
        self,
        *,
        task_id: str,
        content: str,
        run_agent: bool = True,
        run_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(content, str) or not content.strip():
            raise ValidationError("content is required")
        task = self.get_task_or_raise(task_id)
        if qa_crud.get_active_turn(self.connection, task_id) is not None:
            raise ConflictError("task already has an active turn")
        now = utc_now()
        turn_id = f"turn_{uuid.uuid4().hex}"
        message = qa_crud.create_message(
            self.connection,
            message_id=f"msg_{uuid.uuid4().hex}",
            task_id=task_id,
            turn_id=turn_id,
            role="user",
            content=content.strip(),
            metadata={},
            now=now,
        )
        turn = qa_crud.create_turn(
            self.connection,
            turn_id=turn_id,
            task_id=task_id,
            user_message_id=message["id"],
            status="queued",
            now=now,
        )
        task = qa_crud.update_task(
            self.connection,
            task_id=task_id,
            status="running",
            stage="document_processing" if task["stage"] == "document_processing" else "answering",
            active_turn_id=turn_id,
            now=now,
        )
        self._emit_event(task, turn_id=turn_id, event_type="message.created", payload={"role": "user", "content": content.strip()}, now=now)
        self._emit_event(task, turn_id=turn_id, event_type="turn.created", payload={"turn_id": turn_id}, now=now)
        if run_agent:
            self._start_background_worker(
                name=f"qa-turn-{turn_id}",
                target=self._run_turn_when_ready,
                task_id=task_id,
                turn_id=turn_id,
                run_options=run_options,
            )
        return self.serialize_turn(turn)

    def cancel_task(self, task_id: str) -> dict[str, Any]:
        task = self.get_task_or_raise(task_id)
        active_turn = qa_crud.get_active_turn(self.connection, task_id)
        if active_turn is None:
            raise ConflictError("task has no active turn")
        now = utc_now()
        qa_crud.update_turn(
            self.connection,
            turn_id=active_turn["id"],
            status="cancelling",
            now=now,
        )
        completion_id = active_turn.get("agent_completion_id")
        agent_cancel = None
        if completion_id:
            cancel = getattr(self.agent_client, "cancel_document_qa_completion", None)
            if callable(cancel):
                agent_cancel = cancel(completion_id)
        task = qa_crud.update_task(
            self.connection,
            task_id=task_id,
            status="running",
            stage="answering",
            now=now,
        )
        self._emit_event(
            task,
            turn_id=active_turn["id"],
            event_type="turn.cancel_requested",
            payload={"turn_id": active_turn["id"], "agent_cancel": agent_cancel},
            now=now,
        )
        if not completion_id:
            self._finish_turn_cancelled(task_id=task_id, turn_id=active_turn["id"])
        return {"task_id": task_id, "turn_id": active_turn["id"], "status": "cancelling"}

    def get_task_or_raise(self, task_id: str) -> dict[str, Any]:
        task = qa_crud.get_task(self.connection, task_id)
        if task is None:
            raise NotFoundError(f"task not found: {task_id}")
        return task

    def get_task_summary(self, task_id: str) -> dict[str, Any]:
        task = self.get_task_or_raise(task_id)
        return self.serialize_task(task)

    def get_task_detail(self, task_id: str) -> dict[str, Any]:
        task = self.get_task_or_raise(task_id)
        return {
            **self.serialize_task(task),
            "documents": self._review_documents(task_id),
            "source_selectors": self._latest_source_selectors(task_id),
        }

    def list_task_summaries(self, *, limit: int = 20) -> list[dict[str, Any]]:
        return [
            self.serialize_task(task)
            for task in qa_crud.list_tasks(self.connection, limit=max(1, min(limit, 100)))
        ]

    def list_task_events(self, task_id: str, *, after_sequence: int = 0) -> list[dict[str, Any]]:
        self.get_task_or_raise(task_id)
        return [
            self._serialize_event(event)
            for event in qa_crud.list_events(
                self.connection,
                task_id,
                after_sequence=max(0, after_sequence),
            )
        ]

    def serialize_task(self, task: dict[str, Any]) -> dict[str, Any]:
        documents = qa_crud.list_documents(self.connection, task["id"])
        active_turn = qa_crud.get_active_turn(self.connection, task["id"])
        return {
            "task_id": task["id"],
            "status": task["status"],
            "stage": task["stage"],
            "error_message": task["error_message"],
            "document_count": len(documents),
            "active_turn_id": active_turn["id"] if active_turn else None,
            "stream": self._stream_state(task),
            "created_at": task["created_at"],
            "updated_at": task["updated_at"],
        }

    def serialize_turn(self, turn: dict[str, Any]) -> dict[str, Any]:
        return {
            "task_id": turn["task_id"],
            "turn_id": turn["id"],
            "status": turn["status"],
            "agent_completion_id": turn["agent_completion_id"],
        }

    def _run_turn_when_ready(self, *, task_id: str, turn_id: str, run_options: dict[str, Any] | None) -> None:
        while True:
            turn = qa_crud.get_turn(self.connection, turn_id)
            if turn is None or turn["status"] in {"cancelled", "failed"}:
                return
            if turn["status"] == "cancelling":
                self._finish_turn_cancelled(task_id=task_id, turn_id=turn_id)
                return
            task = self.get_task_or_raise(task_id)
            if task["status"] == "failed":
                self._finish_turn_failed(task_id=task_id, turn_id=turn_id, error_message=task["error_message"] or "task failed")
                return
            if task["stage"] != "document_processing":
                break
            time.sleep(0.2)
        self._run_turn(task_id=task_id, turn_id=turn_id, run_options=run_options)

    def _run_turn(self, *, task_id: str, turn_id: str, run_options: dict[str, Any] | None) -> None:
        started_at = utc_now()
        current_turn = qa_crud.get_turn(self.connection, turn_id)
        if current_turn is None or current_turn["status"] in {"cancelled", "failed"}:
            return
        completion_id = f"cmp_{uuid.uuid4().hex}"
        qa_crud.update_turn(
            self.connection,
            turn_id=turn_id,
            status="in_progress",
            agent_completion_id=completion_id,
            now=started_at,
        )
        task = qa_crud.update_task(
            self.connection,
            task_id=task_id,
            status="running",
            stage="answering",
            active_turn_id=turn_id,
            now=started_at,
        )
        self._emit_event(task, turn_id=turn_id, event_type="turn.started", payload={"turn_id": turn_id, "completion_id": completion_id}, now=started_at)

        terminal_type = "completion.completed"
        terminal_status = "completed"
        last_model_message = ""
        try:
            for event in self.agent_client.create_document_qa_completion_stream(
                completion_id=completion_id,
                documents=self._completion_documents(task_id),
                messages=self._completion_messages(task_id),
                memory=loads_json(task["memory_json"], dict(DEFAULT_MEMORY)),
                metadata={"task_id": task_id, "turn_id": turn_id},
                run_options=run_options,
            ):
                if not isinstance(event, dict):
                    continue
                current_turn = qa_crud.get_turn(self.connection, turn_id)
                if current_turn is not None and current_turn["status"] in {"cancelling", "cancelled"}:
                    terminal_type = "completion.cancelled"
                    terminal_status = "cancelled"
                    break
                event_type = str(event.get("type") or "agent.event")
                if event_type == "model_message" and str(event.get("content") or "").strip():
                    last_model_message = str(event["content"])
                if event_type in {"completion.completed", "completion.cancelled", "completion.failed"}:
                    terminal_type = event_type
                    terminal_status = str(event.get("status") or terminal_type.removeprefix("completion."))
                self._emit_agent_event(task_id=task_id, turn_id=turn_id, event=event)
        except Exception as exc:
            current_turn = qa_crud.get_turn(self.connection, turn_id)
            if current_turn is not None and current_turn["status"] in {"cancelling", "cancelled"}:
                self._finish_turn_cancelled(task_id=task_id, turn_id=turn_id)
                return
            self._finish_turn_failed(task_id=task_id, turn_id=turn_id, error_message=str(exc))
            return

        if terminal_type == "completion.failed":
            self._finish_turn_failed(task_id=task_id, turn_id=turn_id, error_message=terminal_status)
            return
        if terminal_type == "completion.cancelled":
            self._finish_turn_cancelled(task_id=task_id, turn_id=turn_id)
            return
        self._finish_turn_completed(task_id=task_id, turn_id=turn_id, assistant_content=last_model_message)

    def _finish_turn_completed(self, *, task_id: str, turn_id: str, assistant_content: str) -> None:
        now = utc_now()
        current_turn = qa_crud.get_turn(self.connection, turn_id)
        if current_turn is not None and current_turn["status"] in {"cancelling", "cancelled"}:
            self._finish_turn_cancelled(task_id=task_id, turn_id=turn_id)
            return
        if assistant_content.strip():
            qa_crud.create_message(
                self.connection,
                message_id=f"msg_{uuid.uuid4().hex}",
                task_id=task_id,
                turn_id=turn_id,
                role="assistant",
                content=assistant_content.strip(),
                metadata={},
                now=now,
            )
        qa_crud.update_turn(self.connection, turn_id=turn_id, status="completed", completed_at=now, now=now)
        task = qa_crud.update_task(
            self.connection,
            task_id=task_id,
            status="ready",
            stage="ready",
            clear_active_turn=True,
            memory=self._updated_memory(task_id),
            now=now,
        )
        self._emit_event(task, turn_id=turn_id, event_type="turn.completed", payload={"turn_id": turn_id}, now=now)

    def _finish_turn_cancelled(self, *, task_id: str, turn_id: str) -> None:
        now = utc_now()
        qa_crud.update_turn(self.connection, turn_id=turn_id, status="cancelled", completed_at=now, now=now)
        task = qa_crud.update_task(
            self.connection,
            task_id=task_id,
            status="ready",
            stage="ready",
            clear_active_turn=True,
            now=now,
        )
        self._emit_event(task, turn_id=turn_id, event_type="turn.cancelled", payload={"turn_id": turn_id}, now=now)

    def _finish_turn_failed(self, *, task_id: str, turn_id: str, error_message: str) -> None:
        now = utc_now()
        qa_crud.update_turn(self.connection, turn_id=turn_id, status="failed", error_message=error_message, completed_at=now, now=now)
        task = qa_crud.update_task(
            self.connection,
            task_id=task_id,
            status="ready",
            stage="ready",
            clear_active_turn=True,
            error_message=error_message,
            now=now,
        )
        self._emit_event(task, turn_id=turn_id, event_type="turn.failed", payload={"turn_id": turn_id, "error_message": error_message}, now=now)

    def _process_document(self, *, task_id: str, upload_file: UploadedFilePayload) -> None:
        file_type = self._infer_file_type(upload_file.filename)
        upload_sha256 = compute_sha256(upload_file.file_bytes)
        result = self.agent_client.process_document(
            file_bytes=upload_file.file_bytes,
            filename=upload_file.filename,
            content_type=upload_file.content_type,
            file_type=file_type,
        )
        now = utc_now()
        document_id = f"doc_{uuid.uuid4().hex}"
        qa_crud.create_document(
            self.connection,
            document_id=document_id,
            task_id=task_id,
            filename=upload_file.filename,
            file_type=file_type,
            content_type=upload_file.content_type,
            upload_size_bytes=len(upload_file.file_bytes),
            upload_sha256=upload_sha256,
            html=result.get("html") or "",
            display_html=result.get("display_html") or result.get("html") or "",
            markdown=result.get("markdown") or "",
            md_list=result.get("md_list") or [],
            blocks=result.get("blocks") or [],
            processor_meta=result.get("meta_info") or {},
            warnings=result.get("warnings") or [],
            now=now,
        )
        self._emit_event(
            self.get_task_or_raise(task_id),
            event_type="document.processed",
            payload={
                "document_id": document_id,
                "filename": upload_file.filename,
                "warning_count": len(result.get("warnings") or []),
            },
            now=now,
        )

    def _completion_documents(self, task_id: str) -> list[dict[str, str]]:
        return [
            {"filename": document["filename"], "html": document["html"]}
            for document in qa_crud.list_documents(self.connection, task_id)
        ]

    def _review_documents(self, task_id: str) -> list[dict[str, str]]:
        return [
            {
                "document_id": document["id"],
                "filename": document["filename"],
                "display_html": document["display_html"],
            }
            for document in qa_crud.list_documents(self.connection, task_id)
        ]

    def _latest_source_selectors(self, task_id: str) -> dict[str, str]:
        source_selectors: dict[str, str] = {}
        for event in qa_crud.list_events(self.connection, task_id, after_sequence=0):
            if event["event_type"] != "agent.event":
                continue
            payload = loads_json(event["payload_json"], {})
            if payload.get("type") != "source_indexed":
                continue
            result = payload.get("result")
            if not isinstance(result, dict):
                continue
            selectors = result.get("source_selectors")
            if isinstance(selectors, dict):
                source_selectors = {str(key): str(value) for key, value in selectors.items()}
        return source_selectors

    def _completion_messages(self, task_id: str) -> list[dict[str, Any]]:
        events_by_turn = self._agent_context_events_by_turn(task_id)
        messages: list[dict[str, Any]] = []
        for message in qa_crud.list_messages(self.connection, task_id):
            if message["role"] == "user":
                messages.append({"role": "user", "content": message["content"]})
                messages.extend(events_by_turn.get(message["turn_id"], []))
            elif message["role"] in {"assistant", "system"} and message["turn_id"] not in events_by_turn:
                messages.append({"role": message["role"], "content": message["content"]})
        return messages

    def _agent_context_events_by_turn(self, task_id: str) -> dict[str, list[dict[str, Any]]]:
        events_by_turn: dict[str, list[dict[str, Any]]] = {}
        pending_tool_calls_by_turn: dict[str, list[dict[str, Any]]] = {}
        for event in qa_crud.list_events(self.connection, task_id, after_sequence=0):
            if event["event_type"] != "agent.event" or not event["turn_id"]:
                continue
            payload = loads_json(event["payload_json"], {})
            if not isinstance(payload, dict):
                continue
            turn_id = str(event["turn_id"])
            event_type = str(payload.get("type") or "")
            if event_type == "model_message":
                content = str(payload.get("content") or "")
                tool_calls = self._openai_tool_calls(payload.get("tool_calls"))
                message: dict[str, Any] = {"role": "assistant", "content": content}
                if tool_calls:
                    message["tool_calls"] = tool_calls
                    pending_tool_calls_by_turn[turn_id] = tool_calls.copy()
                events_by_turn.setdefault(turn_id, []).append(message)
            elif event_type in {"tool_completed", "tool_failed"}:
                tool_call = self._pop_pending_tool_call(pending_tool_calls_by_turn.setdefault(turn_id, []), payload)
                events_by_turn.setdefault(turn_id, []).append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.get("id") or self._fallback_tool_call_id(payload),
                        "name": str(payload.get("tool") or tool_call.get("name") or "tool"),
                        "content": json.dumps(payload.get("result") or {}, ensure_ascii=False),
                    }
                )
        return events_by_turn

    def _openai_tool_calls(self, tool_calls: Any) -> list[dict[str, Any]]:
        if not isinstance(tool_calls, list):
            return []
        normalized = []
        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            name = str(call.get("name") or "")
            if not name:
                continue
            normalized.append(
                {
                    "id": str(call.get("id") or self._fallback_tool_call_id(call)),
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(call.get("args") or {}, ensure_ascii=False),
                    },
                }
            )
        return normalized

    def _pop_pending_tool_call(self, pending_tool_calls: list[dict[str, Any]], payload: dict[str, Any]) -> dict[str, Any]:
        tool_name = str(payload.get("tool") or "")
        if not pending_tool_calls:
            return {}
        for index, call in enumerate(pending_tool_calls):
            function = call.get("function")
            call_name = function.get("name") if isinstance(function, dict) else None
            if call_name == tool_name:
                return pending_tool_calls.pop(index)
        return pending_tool_calls.pop(0)

    def _fallback_tool_call_id(self, payload: dict[str, Any]) -> str:
        source = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return f"call_replayed_{hashlib.sha256(source.encode('utf-8')).hexdigest()[:16]}"

    def _updated_memory(self, task_id: str) -> dict[str, Any]:
        del task_id
        return dict(DEFAULT_MEMORY)

    def _emit_agent_event(self, *, task_id: str, turn_id: str, event: dict[str, Any]) -> None:
        payload = {"agent": "file_extraction_agent", **event}
        self._emit_event(
            self.get_task_or_raise(task_id),
            turn_id=turn_id,
            event_type="agent.event",
            payload=payload,
            now=utc_now(),
        )

    def _emit_event(
        self,
        task: dict[str, Any],
        *,
        event_type: str,
        payload: dict[str, Any],
        turn_id: str | None = None,
        now: str | None = None,
    ) -> dict[str, Any]:
        return qa_crud.create_event(
            self.connection,
            event_id=f"event_{uuid.uuid4().hex}",
            task_id=task["id"],
            turn_id=turn_id,
            event_type=event_type,
            status=task["status"],
            stage=task["stage"],
            payload=payload,
            now=now or utc_now(),
        )

    def _serialize_event(self, event: dict[str, Any]) -> dict[str, Any]:
        return {
            "seq": event["sequence"],
            "task_id": event["task_id"],
            "turn_id": event["turn_id"],
            "type": event["event_type"],
            "status": event["status"],
            "stage": event["stage"],
            "payload": loads_json(event["payload_json"], {}),
            "created_at": event["created_at"],
        }

    def _stream_state(self, task: dict[str, Any]) -> dict[str, Any]:
        state = "running" if qa_crud.get_active_turn(self.connection, task["id"]) else "idle"
        return {
            "state": state,
            "last_event_seq": qa_crud.get_last_event_sequence(self.connection, task["id"]),
        }

    def _infer_file_type(self, filename: str) -> str:
        suffix = Path(filename).suffix.lower().lstrip(".")
        if suffix not in self.settings.supported_file_types:
            raise ValidationError(f"unsupported file type: {suffix or 'unknown'}")
        return suffix

    def _start_background_worker(self, *, name: str, target, **kwargs: Any) -> None:
        thread = threading.Thread(target=target, kwargs=kwargs, name=name, daemon=True)
        thread.start()


TaskService = QaTaskService
