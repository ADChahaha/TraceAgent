"""Define normalized document-processing result dataclasses.

Purpose: hold the shared in-memory result contract across processors.
Input/Output: stores block geometry, block text, and aggregated process results.
How to use: instantiate indirectly through processors or import for tests/type checks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from document_processor.types import FileType


@dataclass(slots=True)
class BoundingBox:
    """Generic bounding box for a text block."""

    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(slots=True)
class ContentBlock:
    """Unified content block returned by all processors."""

    text: str
    page_no: int | None = None
    bbox: BoundingBox | None = None
    kind: str = "text"
    meta_info: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProcessResult:
    """Unified result returned by the processor dispatcher."""

    file_type: FileType
    filename: str | None
    md_list: list[str] = field(default_factory=list)
    markdown: str = ""
    blocks: list[ContentBlock] = field(default_factory=list)
    meta_info: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
