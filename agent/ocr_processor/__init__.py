from __future__ import annotations

from importlib import import_module

from ocr_processor.schemas import BoundingBox, ContentBlock, ProcessResult
from ocr_processor.types import FileType

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
    "DocProcessor": ("ocr_processor.impl.doc.processor", "DocProcessor"),
    "InvalidFileObjectError": ("ocr_processor.impl.base", "InvalidFileObjectError"),
    "PdfProcessor": ("ocr_processor.impl.pdf.processor", "PdfProcessor"),
    "Processor": ("ocr_processor.impl.base", "Processor"),
    "ProcessorDispatcher": ("ocr_processor.impl.dispatcher", "ProcessorDispatcher"),
    "UnsupportedFileTypeError": ("ocr_processor.types", "UnsupportedFileTypeError"),
    "infer_file_type": ("ocr_processor.types", "infer_file_type"),
    "process": ("ocr_processor.processor", "process"),
}


def __getattr__(name: str):
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = _LAZY_EXPORTS[name]
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
