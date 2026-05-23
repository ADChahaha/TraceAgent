from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(tags=["capabilities"])


@router.get("/healthz")
def healthz():
    return {"status": "ok"}


@router.get("/capabilities")
def get_capabilities(request: Request):
    settings = request.app.state.settings
    return {
        "supported_file_types": list(settings.supported_file_types),
        "task_types": [],
        "features": {
            "document_qa": True,
            "multi_turn": True,
            "event_stream": True,
            "cancel": True,
            "multiple_files": True,
        },
    }
