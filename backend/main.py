from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.core.config import BackendSettings
from backend.core.db import ThreadLocalDatabase, initialize_database
from backend.routes import capabilities_router, chat_router
from backend.services.agent_client import AgentClient
from backend.services.document_client import DocumentResourceClient
from backend.services.session_registry import SessionRegistry


def create_app(
    *,
    settings: BackendSettings | None = None,
    agent_client=None,
    document_client=None,
    object_store=None,
) -> FastAPI:
    settings = settings or BackendSettings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database = ThreadLocalDatabase(settings.database_path)
        initialize_database(database.connect())
        resolved_agent_client = agent_client or AgentClient(
            target=settings.agent_service_target,
            timeout_seconds=settings.agent_request_timeout_seconds,
            max_message_bytes=settings.agent_grpc_max_message_bytes,
        )
        owns_document_client = document_client is None and agent_client is None
        resolved_document_client = document_client or agent_client or DocumentResourceClient(
            target=settings.document_service_target,
            timeout_seconds=settings.document_request_timeout_seconds,
            max_message_bytes=settings.document_grpc_max_message_bytes,
        )
        registry = SessionRegistry(
            database=database,
            settings=settings,
            agent_client=resolved_agent_client,
            document_client=resolved_document_client,
            object_store=object_store,
        )
        app.state.database = database
        app.state.agent_client = resolved_agent_client
        app.state.document_client = resolved_document_client
        app.state.session_registry = registry
        try:
            await registry.start()
            yield
        finally:
            await registry.close()
            if agent_client is None:
                await resolved_agent_client.close()
            if owns_document_client:
                await resolved_document_client.close()
            database.close()

    app = FastAPI(
        title="Agent Gate Backend",
        description="会话 completion、快照恢复与轮次取消 API。",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.include_router(chat_router)
    app.include_router(capabilities_router)
    return app


app = create_app()
