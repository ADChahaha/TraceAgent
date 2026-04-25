"""Build the agent service FastAPI app.

Purpose: assemble the HTTP routers exposed by the agent service.
Input/Output: takes no runtime input and returns a configured `FastAPI` app.
How to use: import `app` for ASGI serving or call `create_app()` in tests/startup code.
"""

from fastapi import FastAPI

from routes import document_processor_router, file_extraction_agent_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Agent Service",
        description="文档处理和文档抽取相关 API。",
    )
    app.include_router(document_processor_router)
    app.include_router(file_extraction_agent_router)
    return app


app = create_app()
