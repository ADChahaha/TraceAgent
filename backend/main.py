from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.core.config import BackendSettings
from backend.core.db import ThreadLocalDatabase, initialize_database
from backend.routes import capabilities_router, tasks_router
from backend.services.agent_client import AgentClient
from backend.services.task_service import QaTaskService


def create_app(
    *,
    settings: BackendSettings | None = None,
    agent_client=None,
) -> FastAPI:
    settings = settings or BackendSettings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database = ThreadLocalDatabase(settings.database_path)
        initialize_database(database.connect())
        resolved_agent_client = agent_client or AgentClient(
            base_url=settings.agent_service_base_url,
            timeout_seconds=settings.agent_request_timeout_seconds,
            cancel_timeout_seconds=settings.agent_cancel_timeout_seconds,
        )
        qa_task_service = QaTaskService(
            connection=database,
            settings=settings,
            agent_client=resolved_agent_client,
        )
        app.state.database = database
        app.state.agent_client = resolved_agent_client
        app.state.qa_task_service = qa_task_service
        try:
            yield
        finally:
            database.close()

    app = FastAPI(
        title="Agent Gate Backend",
        description="多文档 QA 任务、事件续传和取消 API。",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.include_router(tasks_router)
    app.include_router(capabilities_router)
    return app


app = create_app()
