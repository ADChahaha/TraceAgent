"""Core data structures for normalized document output.

Purpose: define business-layer result objects shared by processors and adapters.
Input/Output: processors construct these dataclasses; route layer reads attributes
from them and converts them to HTTP responses.
How to use: create ``ProcessResult`` with normalized ``ContentBlock`` instances.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class BoundingBox:
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(slots=True)
class ContentBlock:
    text: str
    page_no: int | None = None
    bbox: BoundingBox | None = None
    kind: str = "text"
    meta_info: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProcessResult:
    file_type: str
    filename: str | None = None
    md_list: list[str] = field(default_factory=list)
    markdown: str = ""
    blocks: list[ContentBlock] = field(default_factory=list)
    meta_info: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
