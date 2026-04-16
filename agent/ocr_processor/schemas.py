from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .types import FileType


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

    processor_name: str
    file_type: FileType
    filename: str | None
    blocks: list[ContentBlock]
    meta_info: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
