from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, File, Form, Request, UploadFile

from backend.routes.errors import raise_http_error
from backend.services.errors import BackendServiceError, ValidationError

router = APIRouter(tags=["tasks"])


@router.post("/tasks")
async def create_task(
    request: Request,
    file: UploadFile = File(...),
    task_type: str = Form(...),
    task_spec: str | None = Form(default=None),
    metadata: str | None = Form(default=None),
):
    service = request.app.state.task_service
    try:
        file_bytes = await file.read()
        return service.create_task(
            file_bytes=file_bytes,
            filename=file.filename or "",
            content_type=file.content_type,
            task_type=task_type,
            task_spec=_parse_required_json_form("task_spec", task_spec),
            metadata=_parse_json_form("metadata", metadata) or {},
        )
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
