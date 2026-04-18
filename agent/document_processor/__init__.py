"""Public exports for the document processing package.

Purpose: expose the stable business API for document normalization.
Input/Output: re-exports process entrypoints, dataclasses, and file-type helpers.
How to use: import from `document_processor` in application code and tests.
"""

from __future__ import annotations

from importlib import import_module

from document_processor.schemas import BoundingBox, ContentBlock, ProcessResult
from document_processor.types import FileType

__all__ = [
    "BoundingBox",
    "ContentBlock",
    "DocProcessor",
    "FileType",
    "InvalidFileObjectError",
    "PdfProcessor",
    "ProcessResult",
    "Processor",
    "ProcessorDispatcher",
    "UnsupportedFileTypeError",
    "infer_file_type",
    "process",
]

_LAZY_EXPORTS = {
    "DocProcessor": ("document_processor.impl.doc.processor", "DocProcessor"),
    "InvalidFileObjectError": ("document_processor.impl.base", "InvalidFileObjectError"),
    "PdfProcessor": ("document_processor.impl.pdf.processor", "PdfProcessor"),
    "Processor": ("document_processor.impl.base", "Processor"),
    "ProcessorDispatcher": ("document_processor.impl.dispatcher", "ProcessorDispatcher"),
    "UnsupportedFileTypeError": ("document_processor.types", "UnsupportedFileTypeError"),
    "infer_file_type": ("document_processor.types", "infer_file_type"),
    "process": ("document_processor.processor", "process"),
}


def __getattr__(name: str):
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = _LAZY_EXPORTS[name]
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
