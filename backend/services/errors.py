from __future__ import annotations


class BackendServiceError(Exception):
    status_code = 500


class ValidationError(BackendServiceError):
    status_code = 422


class NotFoundError(BackendServiceError):
    status_code = 404


class ConflictError(BackendServiceError):
    status_code = 409


class AgentServiceError(BackendServiceError):
    status_code = 502

