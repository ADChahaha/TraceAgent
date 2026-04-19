"""File type definitions and inference helpers for document processing."""

from __future__ import annotations

from enum import Enum
from pathlib import Path


class UnsupportedFileTypeError(ValueError):
    """Raised when document_processor cannot determine a supported file type."""


class FileType(str, Enum):
    PDF = "pdf"
    DOCX = "docx"


def infer_file_type(file_obj, file_type: str | FileType | None = None) -> FileType:
    """Resolve the normalized file type from explicit input or filename."""

    if file_type is not None:
        return _parse_file_type(file_type)

    filename = _extract_filename(file_obj)
    if filename is None:
        raise UnsupportedFileTypeError(
            "Could not determine file type: missing explicit file_type and filename."
        )

    suffix = Path(filename).suffix
    if not suffix:
        raise UnsupportedFileTypeError(
            f"Could not determine file type from filename: {filename!r}."
        )
    return _parse_file_type(suffix)


def _parse_file_type(value: str | FileType) -> FileType:
    normalized = str(value).strip().lower().lstrip(".")
    try:
        return FileType(normalized)
    except ValueError as exc:
        raise UnsupportedFileTypeError(f"Unsupported file type: {value!r}.") from exc


def _extract_filename(file_obj) -> str | None:
    for attr_name in ("filename", "name"):
        value = getattr(file_obj, attr_name, None)
        if isinstance(value, str) and value.strip():
            return value
    return None
