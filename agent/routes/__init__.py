"""Expose HTTP routers for the agent service.

Purpose: provide stable router exports for app assembly.
Input/Output: re-exports router objects from route modules.
How to use: import `document_processor_router` from this package in `main.py`.
"""

from routes.document_processor import router as document_processor_router

__all__ = ["document_processor_router"]
