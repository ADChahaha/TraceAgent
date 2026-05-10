from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.core.config import BackendSettings
from backend.core.db import connect_database, initialize_database
from backend.routes import capabilities_router, experiments_router, reviews_router, tasks_router
from backend.services.agent_client import AgentClient
from backend.services.audit_service import AuditService
from backend.services.review_service import ReviewService
from backend.services.task_service import TaskService


def create_app(
    *,
    settings: BackendSettings | None = None,
    agent_client=None,
) -> FastAPI:
    settings = settings or BackendSettings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        connection = connect_database(settings.database_path)
        initialize_database(connection)
        resolved_agent_client = agent_client or AgentClient(
            base_url=settings.agent_service_base_url,
            timeout_seconds=settings.agent_request_timeout_seconds,
        )
        audit_service = AuditService(connection)
        task_service = TaskService(
            connection=connection,
            settings=settings,
            agent_client=resolved_agent_client,
            audit_service=audit_service,
        )
        review_service = ReviewService(
            connection=connection,
            audit_service=audit_service,
        )
        app.state.database = connection
        app.state.agent_client = resolved_agent_client
        app.state.audit_service = audit_service
        app.state.task_service = task_service
        app.state.review_service = review_service
        try:
            yield
        finally:
            connection.close()

    app = FastAPI(
        title="Agent Gate Backend",
        description="文档治理任务、人工复核和审计 API。",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.include_router(tasks_router)
    app.include_router(reviews_router)
    app.include_router(capabilities_router)
    app.include_router(experiments_router)

    return app


app = create_app()
