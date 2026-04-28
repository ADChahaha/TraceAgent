from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(tags=["capabilities"])


@router.get("/capabilities")
def get_capabilities(request: Request):
    settings = request.app.state.settings
    return {
        "supported_file_types": list(settings.supported_file_types),
        "task_types": [
            {
                "task_type": task_type,
                "display_name": "文明寝室通知抽取"
                if task_type == "civilized_dormitory"
                else task_type,
                "fields": spec.get("fields", []),
            }
            for task_type, spec in settings.task_specs.items()
        ],
        "routes": ["accept", "review", "reject"],
        "review_decisions": ["approve", "revise_and_approve", "reject"],
        "features": {
            "trace": True,
            "review": True,
            "audit": True,
        },
    }

