"""docling PDF 转换和 HTML 导出实现。

实现步骤：

```text
PDF bytes + filename
  -> load_docling_runtime()
  -> build_document_converter()
  -> DocumentStream(name=filename, stream=BytesIO(source_bytes))
  -> converter.convert(...)
  -> conversion_result.document
  -> export_html(document)
  -> document.export_to_html(labels=semantic_docling_labels(), include_annotations=False)
```
"""

from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path
from typing import Any


DocumentStream = None
DocumentConverter = None
InputFormat = None
PdfFormatOption = None
PdfPipelineOptions = None
RapidOcrOptions = None
AcceleratorOptions = None
TableStructureOptions = None


def convert_to_docling_document(source_bytes: bytes, filename: str):
    """把 PDF bytes 包装成 docling DocumentStream 并转换成 docling document。"""

    document_stream_cls, _document_converter_cls, *_ = load_docling_runtime()
    converter = build_document_converter()
    conversion_result = converter.convert(
        document_stream_cls(name=filename, stream=BytesIO(source_bytes))
    )
    return conversion_result.document


def export_html(document) -> str:
    """调用 docling 的 HTML 导出接口并校验返回值。"""

    export_to_html = getattr(document, "export_to_html", None)
    if not callable(export_to_html):
        raise TypeError("docling document must provide export_to_html().")
    html = export_to_html(
        labels=semantic_docling_labels(),
        include_annotations=False,
    )
    if not isinstance(html, str):
        raise TypeError("docling document export_to_html() must return str.")
    return html


def semantic_docling_labels():
    """返回 docling HTML 导出阶段保留的文档语义 label。"""

    from docling_core.types.doc import DocItemLabel

    return {
        DocItemLabel.TITLE,
        DocItemLabel.SECTION_HEADER,
        DocItemLabel.TEXT,
        DocItemLabel.PARAGRAPH,
        DocItemLabel.LIST_ITEM,
        DocItemLabel.TABLE,
        DocItemLabel.CAPTION,
    }


def build_document_converter():
    """构造带 PDF pipeline 配置的 docling DocumentConverter。"""

    (
        _document_stream_cls,
        document_converter_cls,
        input_format_enum,
        pdf_format_option_cls,
        pdf_pipeline_options_cls,
        rapid_ocr_options_cls,
        accelerator_options_cls,
        table_structure_options_cls,
    ) = load_docling_runtime()

    return document_converter_cls(
        format_options={
            input_format_enum.PDF: pdf_format_option_cls(
                pipeline_options=build_pdf_pipeline_options(
                    pdf_pipeline_options_cls,
                    rapid_ocr_options_cls,
                    accelerator_options_cls,
                    table_structure_options_cls,
                )
            )
        }
    )


def load_docling_runtime():
    """延迟导入 docling 运行时，避免模块 import 阶段绑定缓存目录。"""

    global DocumentConverter, DocumentStream, InputFormat, PdfFormatOption, PdfPipelineOptions, RapidOcrOptions, AcceleratorOptions, TableStructureOptions

    configure_runtime_cache_dirs()
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

    if TableStructureOptions is None:
        from docling.datamodel.pipeline_options import (
            TableStructureOptions as _TableStructureOptions,
        )

        TableStructureOptions = _TableStructureOptions

    if AcceleratorOptions is None:
        from docling.datamodel.accelerator_options import (
            AcceleratorOptions as _AcceleratorOptions,
        )

        AcceleratorOptions = _AcceleratorOptions

    return (
        DocumentStream,
        DocumentConverter,
        InputFormat,
        PdfFormatOption,
        PdfPipelineOptions,
        RapidOcrOptions,
        AcceleratorOptions,
        TableStructureOptions,
    )


def build_pdf_pipeline_options(
    pdf_pipeline_options_cls,
    rapid_ocr_options_cls,
    accelerator_options_cls,
    table_structure_options_cls,
):
    """按环境变量组装 docling PDF pipeline 配置。"""

    accelerator_options = build_accelerator_options(accelerator_options_cls)
    return pdf_pipeline_options_cls(
        do_table_structure=True,
        accelerator_options=accelerator_options,
        table_structure_options=build_table_structure_options(
            table_structure_options_cls,
        ),
        ocr_options=rapid_ocr_options_cls(
            backend=resolve_rapidocr_backend(),
            lang=["chinese", "english"],
            force_full_page_ocr=env_flag(
                "DOCUMENT_PROCESSOR_RAPIDOCR_FORCE_FULL_PAGE_OCR",
                False,
            ),
            rec_keys_path=resolve_rapidocr_rec_keys_path(),
            rapidocr_params=build_rapidocr_params(accelerator_options),
        ),
        **pdf_batch_options_from_env(),
    )


def build_accelerator_options(accelerator_options_cls):
    """读取 docling device/thread 环境变量并生成 accelerator options。"""

    kwargs: dict[str, Any] = {}
    device = os.getenv("DOCUMENT_PROCESSOR_DOCLING_DEVICE")
    if device:
        kwargs["device"] = device.strip().lower()

    num_threads = os.getenv("DOCUMENT_PROCESSOR_DOCLING_NUM_THREADS")
    if num_threads:
        kwargs["num_threads"] = parse_positive_int(
            "DOCUMENT_PROCESSOR_DOCLING_NUM_THREADS",
            num_threads,
        )

    return accelerator_options_cls(**kwargs)


def build_table_structure_options(table_structure_options_cls):
    """读取表格 cell matching 开关并生成 table structure options。"""

    return table_structure_options_cls(
        do_cell_matching=env_flag(
            "DOCUMENT_PROCESSOR_PDF_TABLE_DO_CELL_MATCHING",
            True,
        ),
    )


def build_rapidocr_params(accelerator_options) -> dict[str, Any]:
    """生成 RapidOCR 模型目录和运行后端细节参数。"""

    device = str(getattr(accelerator_options, "device", "")).strip().lower()
    return {
        "Global.model_root_dir": package_models_root() / "rapidocr",
        "EngineConfig.onnxruntime.use_coreml": env_flag(
            "DOCUMENT_PROCESSOR_RAPIDOCR_ONNX_USE_COREML",
            False,
        ),
        "EngineConfig.torch.use_mps": env_flag(
            "DOCUMENT_PROCESSOR_RAPIDOCR_TORCH_USE_MPS",
            device == "mps",
        ),
    }


def resolve_rapidocr_backend() -> str:
    """读取并校验 RapidOCR 后端配置。"""

    backend = os.getenv("DOCUMENT_PROCESSOR_RAPIDOCR_BACKEND", "onnxruntime")
    normalized = backend.strip().lower()
    if normalized not in {"onnxruntime", "openvino", "paddle", "torch"}:
        raise ValueError(
            "unsupported DOCUMENT_PROCESSOR_RAPIDOCR_BACKEND: "
            f"{backend!r}; expected one of onnxruntime, openvino, paddle, torch"
        )
    return normalized


def pdf_batch_options_from_env() -> dict[str, int]:
    """读取 PDF OCR/layout/table batch size 环境变量。"""

    env_to_option = {
        "DOCUMENT_PROCESSOR_PDF_OCR_BATCH_SIZE": "ocr_batch_size",
        "DOCUMENT_PROCESSOR_PDF_LAYOUT_BATCH_SIZE": "layout_batch_size",
        "DOCUMENT_PROCESSOR_PDF_TABLE_BATCH_SIZE": "table_batch_size",
    }
    options: dict[str, int] = {}
    for env_name, option_name in env_to_option.items():
        raw_value = os.getenv(env_name)
        if raw_value:
            options[option_name] = parse_positive_int(env_name, raw_value)
    return options


def parse_positive_int(env_name: str, raw_value: str) -> int:
    """把环境变量解析成正整数。"""

    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{env_name} must be a positive integer.") from exc
    if value < 1:
        raise ValueError(f"{env_name} must be a positive integer.")
    return value


def env_flag(name: str, default: bool) -> bool:
    """解析常见布尔环境变量字符串。"""

    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def configure_runtime_cache_dirs() -> None:
    """把 docling/RapidOCR/Hugging Face 默认缓存收口到包内 models 目录。"""

    cache_root = package_models_root()

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


def package_models_root() -> Path:
    """返回 document_processor 包内模型缓存根目录。"""

    return Path(__file__).resolve().parent / "models"


def resolve_rapidocr_rec_keys_path() -> str | None:
    """只在 RapidOCR 字典文件存在时返回路径。"""

    rec_keys_path = package_models_root() / "rapidocr" / "ppocr_keys_v1.txt"
    if rec_keys_path.exists():
        return str(rec_keys_path)
    return None


def resolve_docling_artifacts_path() -> Path:
    """返回 capabilities 接口展示的 docling 模型目录路径。"""

    return Path(os.environ.get("DOCLING_CACHE_DIR") or package_models_root() / "docling")
