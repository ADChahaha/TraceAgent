from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, BackgroundTasks, File, Form, Request, UploadFile

from backend.routes.errors import raise_http_error
from backend.services.errors import BackendServiceError, ValidationError

router = APIRouter(tags=["tasks"])


@router.get("/tasks")
def list_tasks(request: Request, limit: int = 20):
    try:
        return {"tasks": request.app.state.task_service.list_task_summaries(limit=limit)}
    except BackendServiceError as exc:
        raise_http_error(exc)


@router.post("/tasks")
async def create_task(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile | None = File(default=None),
    files: list[UploadFile] | None = File(default=None),
    task_type: str = Form(...),
    task_spec: str | None = Form(default=None),
    metadata: str | None = Form(default=None),
):
    service = request.app.state.task_service
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
        parsed_task_spec = _parse_required_json_form("task_spec", task_spec)
        parsed_metadata = _parse_json_form("metadata", metadata) or {}
        created = service.create_task(
            files=upload_payloads,
            task_type=task_type,
            task_spec=parsed_task_spec,
            metadata=parsed_metadata,
            run_pipeline=False,
        )
        background_tasks.add_task(
            service.run_created_task,
            task_id=created["task_id"],
            upload_files=upload_payloads,
            task_type=task_type,
            task_spec=parsed_task_spec,
            metadata=parsed_metadata,
        )
        return created
    except BackendServiceError as exc:
        raise_http_error(exc)


@router.get("/tasks/{task_id}")
def get_task(task_id: str, request: Request):
    try:
        return request.app.state.task_service.get_task_summary(task_id)
    except BackendServiceError as exc:
        raise_http_error(exc)


@router.get("/tasks/{task_id}/result")
def get_result(task_id: str, request: Request):
    try:
        return request.app.state.task_service.get_result(task_id)
    except BackendServiceError as exc:
        raise_http_error(exc)


@router.get("/tasks/{task_id}/trace")
def get_trace(task_id: str, request: Request):
    try:
        return request.app.state.task_service.get_trace(task_id)
    except BackendServiceError as exc:
        raise_http_error(exc)


@router.get("/tasks/{task_id}/replay")
def get_replay(task_id: str, request: Request):
    try:
        return request.app.state.task_service.get_replay(task_id)
    except BackendServiceError as exc:
        raise_http_error(exc)


@router.get("/tasks/{task_id}/audit")
def get_audit(task_id: str, request: Request):
    try:
        task = request.app.state.task_service.get_task_or_raise(task_id)
        return request.app.state.audit_service.list_audit(task)
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


def _parse_required_json_form(name: str, value: str | None) -> dict[str, Any]:
    parsed = _parse_json_form(name, value)
    if parsed is None:
        raise ValidationError(f"{name} is required")
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
