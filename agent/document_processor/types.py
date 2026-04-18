"""Define supported document file types and inference helpers.

Purpose: normalize file-type handling before dispatching to processors.
Input/Output: accepts filenames/content types/file-like objects and returns `FileType`.
How to use: call `infer_file_type(...)` or `FileType.normalize(...)` before processing.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any


class UnsupportedFileTypeError(ValueError):
    """Raised when the processor receives an unsupported file type."""


class FileType(str, Enum):
    PDF = "pdf"
    DOC = "doc"
    DOCX = "docx"

    @classmethod
    def normalize(cls, value: str | FileType) -> FileType:
        if isinstance(value, cls):
            return value

        normalized = value.strip().lower().lstrip(".")
        try:
            return cls(normalized)
        except ValueError as exc:
            supported = ", ".join(item.value for item in cls)
            raise UnsupportedFileTypeError(
                f"Unsupported file type: {value}. Supported types: {supported}"
            ) from exc


def infer_file_type(file_obj: Any) -> FileType:
    """
    Infer file type from a file-like object.

    Priority:
    1. `filename`
    2. inner `.file.name` (e.g. FastAPI UploadFile)
    3. `content_type`
    """

    filename = getattr(file_obj, "filename", None)
    if filename:
        return _infer_from_filename(str(filename))

    direct_name = getattr(file_obj, "name", None)
    if direct_name:
        return _infer_from_filename(str(direct_name))

    inner_file = getattr(file_obj, "file", None)
    inner_name = getattr(inner_file, "name", None)
    if inner_name:
        return _infer_from_filename(str(inner_name))

    content_type = getattr(file_obj, "content_type", None)
    if content_type:
        return _infer_from_content_type(str(content_type))

    raise UnsupportedFileTypeError(
        "Cannot infer file type from file object. Please provide a file with a valid filename or content_type."
    )


def _infer_from_filename(filename: str) -> FileType:
    extension = Path(filename).suffix.lower()
    match extension:
        case ".pdf":
            return FileType.PDF
        case ".doc":
            return FileType.DOC
        case ".docx":
            return FileType.DOCX
        case _:
            raise UnsupportedFileTypeError(f"Unsupported file extension: {extension or 'unknown'}")


def _infer_from_content_type(content_type: str) -> FileType:
    normalized = content_type.lower()
    if normalized == "application/pdf":
        return FileType.PDF
    if normalized == "application/msword":
        return FileType.DOC
    if normalized == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return FileType.DOCX

    raise UnsupportedFileTypeError(f"Unsupported content_type: {content_type}")
