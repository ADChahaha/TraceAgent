from __future__ import annotations

from importlib import import_module

__all__ = ["DocProcessor", "docling_adapter"]

_LAZY_EXPORTS = {
    "DocProcessor": ("ocr_processor.impl.doc.processor", "DocProcessor"),
    "docling_adapter": ("ocr_processor.impl.doc.docling_adapter", None),
}


def __getattr__(name: str):
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = _LAZY_EXPORTS[name]
    module = import_module(module_name)
    value = module if attr_name is None else getattr(module, attr_name)
    globals()[name] = value
    return value
