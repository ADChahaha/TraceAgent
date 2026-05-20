"""创建 agent service 的 FastAPI 应用并挂载各阶段 HTTP router。"""

from fastapi import FastAPI

from routes import (
    document_processor_router,
    file_extraction_agent_router,
)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Agent Service",
        description="文档处理和文档抽取相关 API。",
    )
    app.include_router(document_processor_router)
    app.include_router(file_extraction_agent_router)
    return app


app = create_app()
