from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from backend.routes.errors import raise_http_error
from backend.services.errors import BackendServiceError

router = APIRouter(tags=["reviews"])


class ReviewFieldRequest(BaseModel):
    field_name: str
    review_value: Any | None = None
    comment: str | None = None


class ReviewSubmitRequest(BaseModel):
    decision: Literal["approve", "revise_and_approve", "reject"]
    fields: list[ReviewFieldRequest] = Field(default_factory=list)
    comment: str | None = None
    reviewer: str | None = None


@router.get("/tasks/{task_id}/review")
def get_review(task_id: str, request: Request):
    try:
        return request.app.state.review_service.get_review_handoff(task_id)
    except BackendServiceError as exc:
        raise_http_error(exc)


@router.post("/tasks/{task_id}/review")
def submit_review(task_id: str, payload: ReviewSubmitRequest, request: Request):
    try:
        return request.app.state.review_service.submit_review(
            task_id=task_id,
            decision=payload.decision,
            fields=[field.model_dump() for field in payload.fields],
            comment=payload.comment,
            reviewer=payload.reviewer,
        )
    except BackendServiceError as exc:
        raise_http_error(exc)

