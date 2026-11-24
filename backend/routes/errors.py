from __future__ import annotations

import logging

from fastapi import HTTPException

from backend.services.errors import BackendServiceError
from backend.services.user_errors import format_http_error

logger = logging.getLogger(__name__)


def raise_http_error(exc: BackendServiceError) -> None:
    if exc.status_code >= 500:
        logger.warning("Backend request failed (%s %s): %s", exc.status_code, type(exc).__name__, exc)
    raise HTTPException(status_code=exc.status_code, detail=format_http_error(exc))

