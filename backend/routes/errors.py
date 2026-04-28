from __future__ import annotations

from fastapi import HTTPException

from backend.services.errors import BackendServiceError


def raise_http_error(exc: BackendServiceError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=str(exc))

