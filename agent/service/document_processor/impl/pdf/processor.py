"""基于 docling 的 PDF 处理器。

实现步骤：

```text
调用方把 pdf file_obj 交给 `PdfProcessor.process(...)`
  -> 基类先校验 file_obj 至少提供可调用的 read()
  -> `PdfProcessor` 读取 PDF 二进制，并从 filename/name 推出输出文件名，没有就回退成 `document.pdf`
  -> 把二进制包装成 `DocumentStream(name, BytesIO(...))`
  -> 调用 `DocumentConverter.convert(...)` 走 docling 的唯一解析链路
  -> 从 `conversion_result.document.export_to_markdown()` 取整篇 markdown
  -> 遍历 `document.iterate_items()`，把标题/正文/表格节点归一化成 `ContentBlock`
  -> 从 provenance 提取 page_no 和 bbox
  -> 返回统一的 `ProcessResult(file_type, filename, md_list, markdown, blocks, meta_info)`
```
"""

from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path
from typing import Any

from service.document_processor.impl.base import BaseDocumentProcessor
from service.document_processor.schemas import BoundingBox, ContentBlock, ProcessResult
from service.document_processor.types import FileType

DocumentStream = None
DocumentConverter = None
InputFormat = None
PdfFormatOption = None
PdfPipelineOptions = None
RapidOcrOptions = None


class PdfProcessor(BaseDocumentProcessor):
    """使用 docling 解析 PDF 的具体处理器。"""

    file_type = FileType.PDF

    def __init__(self) -> None:
        (
            document_stream_cls,
            document_converter_cls,
            input_format_enum,
            pdf_format_option_cls,
            pdf_pipeline_options_cls,
            rapid_ocr_options_cls,
        ) = _load_docling_runtime()
        self._document_stream_cls = document_stream_cls
        self._converter = document_converter_cls(
            format_options={
                input_format_enum.PDF: pdf_format_option_cls(
                    pipeline_options=pdf_pipeline_options_cls(
                        do_table_structure=True,
                        ocr_options=rapid_ocr_options_cls(
                            backend="torch",
                            lang=["chinese", "english"],
                            rec_keys_path=str(
                                _package_models_root() / "rapidocr" / "ppocr_keys_v1.txt"
                            ),
                            rapidocr_params={
                                "Global.model_root_dir": (
                                    _package_models_root() / "rapidocr"
                                )
                            },
                        ),
                    )
                )
            }
        )

    def _process(self, file_obj):
        filename = self._resolve_filename(file_obj)
        source_bytes = self._read_source_bytes(file_obj)
        conversion_result = self._converter.convert(
            self._document_stream_cls(name=filename, stream=BytesIO(source_bytes))
        )
        document = conversion_result.document
        markdown = document.export_to_markdown()
        blocks = self._build_blocks(document)

        return ProcessResult(
            file_type=self.file_type.value,
            filename=filename,
            md_list=[markdown] if markdown else [],
            markdown=markdown,
            blocks=blocks,
            meta_info={
                "block_count": len(blocks),
                "page_count": len(
                    {
                        block.page_no
                        for block in blocks
                        if block.page_no is not None
                    }
                ),
            },
        )

    @staticmethod
    def _resolve_filename(file_obj) -> str:
        filename = getattr(file_obj, "filename", None) or getattr(file_obj, "name", None)
        if filename:
            return Path(str(filename)).name
        return "document.pdf"

    @staticmethod
    def _read_source_bytes(file_obj) -> bytes:
        if hasattr(file_obj, "seek"):
            file_obj.seek(0)
        source_bytes = file_obj.read()
        if hasattr(file_obj, "seek"):
            file_obj.seek(0)
        return source_bytes

    @classmethod
    def _build_blocks(cls, document) -> list[ContentBlock]:
        blocks: list[ContentBlock] = []

        for item, _level in document.iterate_items():
            text = cls._extract_text(item, document)
            if not text:
                continue

            provenance = cls._extract_provenance(item)
            page_no = getattr(provenance, "page_no", None) if provenance else None
            blocks.append(
                ContentBlock(
                    text=text,
                    page_no=page_no,
                    bbox=cls._to_bbox(getattr(provenance, "bbox", None)),
                    kind=cls._normalize_kind(getattr(item, "label", None)),
                )
            )

        return blocks

    @staticmethod
    def _extract_text(item: Any, document: Any) -> str:
        text = getattr(item, "text", None)
        if isinstance(text, str):
            normalized = " ".join(text.split())
            if normalized:
                return normalized

        export_to_markdown = getattr(item, "export_to_markdown", None)
        if callable(export_to_markdown):
            try:
                markdown = export_to_markdown()
            except TypeError:
                markdown = export_to_markdown(document)
            if isinstance(markdown, str):
                normalized = " ".join(markdown.split())
                if normalized:
                    return normalized

        return ""

    @staticmethod
    def _extract_provenance(item: Any):
        provenance = getattr(item, "prov", None)
        if isinstance(provenance, list) and provenance:
            return provenance[0]
        return None

    @staticmethod
    def _to_bbox(raw_bbox: Any) -> BoundingBox | None:
        if raw_bbox is None:
            return None

        try:
            return BoundingBox(
                x0=float(raw_bbox.l),
                y0=float(raw_bbox.t),
                x1=float(raw_bbox.r),
                y1=float(raw_bbox.b),
            )
        except (AttributeError, TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_kind(label: Any) -> str:
        normalized = str(label).strip().lower() if label is not None else "text"
        if normalized in {"title", "section_header"}:
            return "section_header"
        if normalized == "table":
            return "table"
        return "text"


def _load_docling_runtime():
    global DocumentConverter, DocumentStream, InputFormat, PdfFormatOption, PdfPipelineOptions, RapidOcrOptions

    _configure_runtime_cache_dirs()
    if DocumentStream is None:
        from docling.datamodel.base_models import DocumentStream as _DocumentStream
        DocumentStream = _DocumentStream

    if DocumentConverter is None:
        from docling.document_converter import DocumentConverter as _DocumentConverter
        DocumentConverter = _DocumentConverter

    if InputFormat is None:
        from docling.datamodel.base_models import InputFormat as _InputFormat
        InputFormat = _InputFormat

    if PdfFormatOption is None:
        from docling.document_converter import PdfFormatOption as _PdfFormatOption
        PdfFormatOption = _PdfFormatOption

    if PdfPipelineOptions is None:
        from docling.datamodel.pipeline_options import (
            PdfPipelineOptions as _PdfPipelineOptions,
        )
        PdfPipelineOptions = _PdfPipelineOptions

    if RapidOcrOptions is None:
        from docling.datamodel.pipeline_options import RapidOcrOptions as _RapidOcrOptions
        RapidOcrOptions = _RapidOcrOptions

    return (
        DocumentStream,
        DocumentConverter,
        InputFormat,
        PdfFormatOption,
        PdfPipelineOptions,
        RapidOcrOptions,
    )


def _configure_runtime_cache_dirs() -> None:
    cache_root = _package_models_root()

    if "DOCLING_CACHE_DIR" not in os.environ:
        os.environ["DOCLING_CACHE_DIR"] = str(cache_root / "docling")

    if "RAPIDOCR_MODEL_ROOT" not in os.environ:
        os.environ["RAPIDOCR_MODEL_ROOT"] = str(cache_root / "rapidocr")

    if (
        "HF_HOME" not in os.environ
        and "HF_HUB_CACHE" not in os.environ
        and "HUGGINGFACE_HUB_CACHE" not in os.environ
    ):
        os.environ["HF_HOME"] = str(cache_root / "huggingface")

    Path(os.environ["DOCLING_CACHE_DIR"]).mkdir(parents=True, exist_ok=True)
    Path(os.environ["RAPIDOCR_MODEL_ROOT"]).mkdir(parents=True, exist_ok=True)

    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        Path(hf_home).mkdir(parents=True, exist_ok=True)


def _package_models_root() -> Path:
    return Path(__file__).resolve().parent / "models"


def resolve_docling_artifacts_path() -> Path:
    """返回 capabilities 接口展示的 docling 模型目录路径。"""

    return Path(os.environ.get("DOCLING_CACHE_DIR") or _package_models_root() / "docling")
