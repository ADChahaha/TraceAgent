"""集中导出 agent service 的 HTTP router。"""

from routes.document_resources import router as document_resources_router
from routes.file_extraction_agent import router as file_extraction_agent_router

__all__ = [
    "document_resources_router",
    "file_extraction_agent_router",
]
