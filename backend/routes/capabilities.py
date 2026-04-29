from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(tags=["capabilities"])


@router.get("/capabilities")
def get_capabilities(request: Request):
    settings = request.app.state.settings
    return {
        "supported_file_types": list(settings.supported_file_types),
        "task_types": [],
        "routes": ["accept", "review", "reject"],
        "review_decisions": ["approve", "revise_and_approve", "reject"],
        "features": {
            "trace": True,
            "review": True,
            "audit": True,
            "external_task_spec": True,
            "multiple_files": True,
        },
    }
