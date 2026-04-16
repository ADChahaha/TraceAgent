from importlib import import_module

from ocr_processor.impl.base import InvalidFileObjectError, Processor
from ocr_processor.impl.dispatcher import ProcessorDispatcher
from ocr_processor.schemas import BoundingBox, ContentBlock, ProcessResult
from ocr_processor.types import FileType, UnsupportedFileTypeError, infer_file_type

_dispatcher = ProcessorDispatcher()


def process(file_obj, file_type: str | FileType | None = None) -> ProcessResult:
    """
    Public convenience entrypoint.

    Typical usage:
        from ocr_processor.processor import process
        result = process(file_obj)
    """

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
    "DocProcessor": ("ocr_processor.impl.doc.processor", "DocProcessor"),
    "PdfProcessor": ("ocr_processor.impl.pdf.processor", "PdfProcessor"),
}


def __getattr__(name: str):
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = _LAZY_EXPORTS[name]
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
