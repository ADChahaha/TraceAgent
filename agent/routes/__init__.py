"""Expose HTTP routers for the agent service.

Purpose: provide stable router exports for app assembly.
Input/Output: re-exports router objects from route modules.
How to use: import router objects from this package in `main.py`.
"""

from routes.document_processor import router as document_processor_router
from routes.file_extraction_agent import router as file_extraction_agent_router

__all__ = ["document_processor_router", "file_extraction_agent_router"]
