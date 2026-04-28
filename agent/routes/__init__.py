"""集中导出 agent service 的 HTTP router。"""

from routes.document_processor import router as document_processor_router
from routes.file_extraction_agent import router as file_extraction_agent_router
from routes.route_policy_agent import router as route_policy_agent_router

__all__ = [
    "document_processor_router",
    "file_extraction_agent_router",
    "route_policy_agent_router",
]
