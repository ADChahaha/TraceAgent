"""Provide shared file-object adaptation for concrete processors.

Purpose: turn upload-like objects into bytes/filenames before format-specific work.
Input/Output: accepts file-like wrappers and returns normalized stream metadata/bytes.
How to use: subclass `Processor` and implement `_process_content(...)`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import inspect
from pathlib import Path
from typing import Any, Protocol

from document_processor.schemas import ProcessResult
from document_processor.types import FileType


class InvalidFileObjectError(TypeError):
    """Raised when the given object cannot be treated as a readable file."""


class ReadableFile(Protocol):
    """Minimal protocol for file-like objects accepted by the processor."""

    def read(self, size: int = -1) -> bytes: ...

    def seek(self, offset: int, whence: int = 0) -> int: ...


class Processor(ABC):
    """
    Base processor with a common `process(file_obj)` entrypoint.

    The caller is expected to choose the processor through `ProcessorDispatcher`
    using an explicit file type, instead of guessing from the filename.
    """

    file_type: FileType

    def process(self, file_obj: Any) -> ProcessResult:
        stream = self._resolve_stream(file_obj)
        filename = self._resolve_filename(file_obj, stream)
        content = self._read_bytes(stream)
        return self._process_content(
            content=content,
            filename=filename,
        )

    @abstractmethod
    def _process_content(
        self,
        *,
        content: bytes,
        filename: str | None,
    ) -> ProcessResult:
        """Process file bytes and return a unified result."""

    def _resolve_stream(self, file_obj: Any) -> ReadableFile:
        """
        Support either:
        - a plain file-like object
        - an object like FastAPI UploadFile, where the real stream is in `.file`
        """

        inner_file = getattr(file_obj, "file", None)
        direct_read = getattr(file_obj, "read", None)

        # Starlette/FastAPI UploadFile exposes an async `.read()`, but the actual
        # synchronous stream still lives under `.file`.
        if inner_file is not None and hasattr(inner_file, "read") and (
            direct_read is None or inspect.iscoroutinefunction(direct_read)
        ):
            return inner_file

        if direct_read is not None and not inspect.iscoroutinefunction(direct_read):
            return file_obj

        raise InvalidFileObjectError(
            "file_obj must be readable or expose a readable `.file` attribute"
        )

    def _resolve_filename(self, file_obj: Any, stream: ReadableFile) -> str | None:
        filename = getattr(file_obj, "filename", None)
        if filename:
            return str(filename)

        stream_name = getattr(stream, "name", None)
        if stream_name:
            return Path(str(stream_name)).name

        return None

    def _read_bytes(self, stream: ReadableFile) -> bytes:
        current_pos = None
        if hasattr(stream, "seek"):
            try:
                current_pos = stream.seek(0, 1)
                stream.seek(0)
            except OSError:
                current_pos = None

        content = stream.read()
        if isinstance(content, str):
            content = content.encode("utf-8")

        if current_pos is not None:
            try:
                stream.seek(current_pos)
            except OSError:
                pass

        return content
