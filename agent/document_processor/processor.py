"""Provide the package-level document processing entrypoint.

Purpose: route file-like objects into the correct document processor.
Input/Output: accepts a readable file object plus optional file type and returns
`ProcessResult`.
How to use: call `process(file_obj, file_type=None)` from Python business code.
"""

from importlib import import_module

from document_processor.impl.base import InvalidFileObjectError, Processor
from document_processor.impl.dispatcher import ProcessorDispatcher
from document_processor.schemas import BoundingBox, ContentBlock, ProcessResult
from document_processor.types import FileType, UnsupportedFileTypeError, infer_file_type

_dispatcher = ProcessorDispatcher()


def process(file_obj, file_type: str | FileType | None = None) -> ProcessResult:
    """Process one document into normalized markdown and block outputs."""

    return _dispatcher.process(file_obj=file_obj, file_type=file_type)

__all__ = [
    "BoundingBox",
    "ContentBlock",
    "FileType",
    "InvalidFileObjectError",
    "ProcessResult",
    "Processor",
    "ProcessorDispatcher",
    "UnsupportedFileTypeError",
    "infer_file_type",
    "process",
]

_LAZY_EXPORTS = {
    "DocProcessor": ("document_processor.impl.doc.processor", "DocProcessor"),
    "PdfProcessor": ("document_processor.impl.pdf.processor", "PdfProcessor"),
}


def __getattr__(name: str):
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = _LAZY_EXPORTS[name]
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
