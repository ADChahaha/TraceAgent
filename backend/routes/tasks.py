from __future__ import annotations

import json
import time
from typing import Any

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from backend.routes.errors import raise_http_error
from backend.services.errors import BackendServiceError, ValidationError

router = APIRouter(tags=["qa-tasks"])


class QaInputRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str
    run_options: dict[str, Any] | None = None


@router.post("/qa/tasks")
async def create_qa_task(
    request: Request,
    file: UploadFile | None = File(default=None),
    files: list[UploadFile] | None = File(default=None),
    metadata: str | None = None,
):
    service = request.app.state.qa_task_service
    try:
        upload_files = _collect_upload_files(file=file, files=files)
        upload_payloads = [
            service.upload_file_payload(
                file_bytes=await upload_file.read(),
                filename=upload_file.filename or "",
                content_type=upload_file.content_type,
            )
            for upload_file in upload_files
        ]
        return service.create_task(files=upload_payloads, metadata=_parse_json_form("metadata", metadata) or {})
    except BackendServiceError as exc:
        raise_http_error(exc)


@router.get("/qa/tasks")
def list_qa_tasks(request: Request, limit: int = 20):
    try:
        return {"tasks": request.app.state.qa_task_service.list_task_summaries(limit=limit)}
    except BackendServiceError as exc:
        raise_http_error(exc)


@router.get("/qa/tasks/{task_id}")
def get_qa_task(task_id: str, request: Request):
    try:
        return request.app.state.qa_task_service.get_task_detail(task_id)
    except BackendServiceError as exc:
        raise_http_error(exc)


@router.post("/qa/tasks/{task_id}/inputs")
def create_qa_input(task_id: str, request: Request, body: QaInputRequest):
    try:
        return request.app.state.qa_task_service.create_input(
            task_id=task_id,
            content=body.content,
            run_options=body.run_options,
        )
    except BackendServiceError as exc:
        raise_http_error(exc)


@router.get("/qa/tasks/{task_id}/events")
def get_qa_events(task_id: str, request: Request, after_seq: int = 0):
    try:
        request.app.state.qa_task_service.get_task_or_raise(task_id)
    except BackendServiceError as exc:
        raise_http_error(exc)
    return StreamingResponse(
        _iter_sse_events(request=request, task_id=task_id, after_seq=after_seq),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/qa/tasks/{task_id}/cancel")
def cancel_qa_task(task_id: str, request: Request):
    try:
        return request.app.state.qa_task_service.cancel_task(task_id)
    except BackendServiceError as exc:
        raise_http_error(exc)


def _parse_json_form(name: str, value: str | None) -> dict[str, Any] | None:
    if value is None or not value.strip():
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"{name} must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValidationError(f"{name} must be a JSON object")
    return parsed


def _collect_upload_files(
    *,
    file: UploadFile | None,
    files: list[UploadFile] | None,
) -> list[UploadFile]:
    upload_files = [*(files or [])]
    if file is not None:
        upload_files.append(file)
    if not upload_files:
        raise ValidationError("at least one file is required")
    return upload_files


def _iter_sse_events(
    *,
    request: Request,
    task_id: str,
    after_seq: int,
    poll_interval_seconds: float = 0.2,
):
    last_seq = max(0, after_seq)
    service = request.app.state.qa_task_service
    while True:
        events = service.list_task_events(task_id, after_sequence=last_seq)
        for event in events:
            last_seq = event["seq"]
            event_name = event["type"]
            data = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
            yield f"event: {event_name}\n"
            yield f"id: {last_seq}\n"
            yield f"data: {data}\n\n"

        summary = service.get_task_summary(task_id)
        if summary["stream"]["state"] == "idle" and summary["stream"]["last_event_seq"] <= last_seq:
            break
        time.sleep(poll_interval_seconds)
