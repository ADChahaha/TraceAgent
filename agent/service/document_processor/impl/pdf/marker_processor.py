"""基于 Marker 的 PDF 处理器。

实现步骤：

```text
调用方把 pdf file_obj 交给 `PdfMarkerProcessor.process(...)`
  -> 复用 `PdfProcessor` 的文件名解析和二进制读取 helper，但不初始化 docling
  -> 先把 Marker / Surya / Hugging Face 缓存目录收口到 `impl/pdf/models/marker`
  -> 将传入的 PDF 二进制写入临时 pdf 文件，因为 Marker 当前入口接收文件路径
  -> 调用 Marker converter 生成 rendered document
  -> 用 `marker.output.text_from_rendered(...)` 导出 markdown
  -> 按 markdown 结构轻量拆出标题、表格和正文 `ContentBlock`
  -> 返回统一的 `ProcessResult(meta_info.ocr_engine="marker")`
```
"""

from __future__ import annotations

import os
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Any, Callable

from service.document_processor.impl.pdf.processor import (
    PdfProcessor,
    _package_models_root,
)
from service.document_processor.schemas import ContentBlock, ProcessResult


class PdfMarkerProcessor(PdfProcessor):
    """用 Marker/marker-pdf 解析扫描版 PDF，并输出统一结果结构。"""

    def __init__(
        self,
        *,
        converter: Callable[[str], Any] | None = None,
        text_extractor: Callable[[Any], tuple[str, str, dict[str, Any]]] | None = None,
    ) -> None:
        marker_runtime = None
        if converter is None or text_extractor is None:
            marker_runtime = _load_marker_runtime()

        self._converter = converter
        if self._converter is None and marker_runtime is not None:
            self._converter = _build_marker_converter(marker_runtime)

        self._text_extractor = text_extractor
        if self._text_extractor is None and marker_runtime is not None:
            self._text_extractor = marker_runtime["text_from_rendered"]

    def _process(self, file_obj):
        filename = self._resolve_filename(file_obj)
        source_bytes = self._read_source_bytes(file_obj)

        with tempfile.TemporaryDirectory(prefix="document_processor_marker_") as tmp_dir:
            pdf_path = Path(tmp_dir) / filename
            pdf_path.write_bytes(source_bytes)
            rendered = self._converter(str(pdf_path))

        markdown, extension, images = self._text_extractor(rendered)
        markdown = markdown.strip()
        blocks = _blocks_from_markdown(markdown)
        page_count = _resolve_page_count(rendered, source_bytes)

        return ProcessResult(
            file_type=self.file_type.value,
            filename=filename,
            md_list=[markdown] if markdown else [],
            markdown=markdown,
            blocks=blocks,
            meta_info={
                "ocr_engine": "marker",
                "marker_output_format": extension,
                "block_count": len(blocks),
                "page_count": page_count,
                "image_count": len(images),
            },
        )


def _load_marker_runtime() -> dict[str, Any]:
    _configure_marker_runtime_cache_dirs()
    try:
        from marker.config.parser import ConfigParser
        from marker.models import create_model_dict
        from marker.output import text_from_rendered
    except ImportError as exc:
        raise RuntimeError(
            "PdfMarkerProcessor requires marker-pdf. Install it in an isolated "
            "runtime before using DOCUMENT_PROCESSOR_PDF_ENGINE=pdf-marker."
        ) from exc

    return {
        "ConfigParser": ConfigParser,
        "create_model_dict": create_model_dict,
        "text_from_rendered": text_from_rendered,
    }


def _build_marker_converter(marker_runtime: dict[str, Any]) -> Callable[[str], Any]:
    config_parser = marker_runtime["ConfigParser"](
        {
            "output_format": "markdown",
            "force_ocr": _env_flag("DOCUMENT_PROCESSOR_MARKER_FORCE_OCR", True),
            "disable_multiprocessing": _env_flag(
                "DOCUMENT_PROCESSOR_MARKER_DISABLE_MULTIPROCESSING",
                True,
            ),
        }
    )
    return config_parser.get_converter_cls()(
        config=config_parser.generate_config_dict(),
        artifact_dict=marker_runtime["create_model_dict"](),
    )


def _configure_marker_runtime_cache_dirs() -> None:
    cache_root = _package_models_root() / "marker"
    cache_root.mkdir(parents=True, exist_ok=True)

    if "MODEL_CACHE_DIR" not in os.environ:
        os.environ["MODEL_CACHE_DIR"] = str(cache_root)

    if (
        "HF_HOME" not in os.environ
        and "HF_HUB_CACHE" not in os.environ
        and "HUGGINGFACE_HUB_CACHE" not in os.environ
    ):
        os.environ["HF_HOME"] = str(cache_root / "huggingface")

    if "XDG_CACHE_HOME" not in os.environ:
        os.environ["XDG_CACHE_HOME"] = str(cache_root / "xdg")

    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

    Path(os.environ["MODEL_CACHE_DIR"]).mkdir(parents=True, exist_ok=True)
    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        Path(hf_home).mkdir(parents=True, exist_ok=True)
    Path(os.environ["XDG_CACHE_HOME"]).mkdir(parents=True, exist_ok=True)


def _env_flag(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _blocks_from_markdown(markdown: str) -> list[ContentBlock]:
    blocks: list[ContentBlock] = []
    lines = markdown.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue

        if line.startswith("#"):
            heading_text = line.lstrip("#").strip()
            if heading_text:
                blocks.append(ContentBlock(text=heading_text, kind="section_header"))
            index += 1
            continue

        if _looks_like_table_row(line):
            table_lines = [line]
            index += 1
            while index < len(lines) and _looks_like_table_row(lines[index].strip()):
                table_lines.append(lines[index].strip())
                index += 1
            blocks.append(ContentBlock(text="\n".join(table_lines), kind="table"))
            continue

        paragraph_lines = [line]
        index += 1
        while index < len(lines):
            next_line = lines[index].strip()
            if (
                not next_line
                or next_line.startswith("#")
                or _looks_like_table_row(next_line)
            ):
                break
            paragraph_lines.append(next_line)
            index += 1
        blocks.append(ContentBlock(text=" ".join(paragraph_lines), kind="text"))

    return blocks


def _looks_like_table_row(line: str) -> bool:
    return line.startswith("|") and line.endswith("|") and line.count("|") >= 2


def _resolve_page_count(rendered: Any, source_bytes: bytes) -> int:
    rendered_pages = getattr(rendered, "pages", None)
    if rendered_pages:
        return len(rendered_pages)

    try:
        import pypdfium2 as pdfium

        return len(pdfium.PdfDocument(BytesIO(source_bytes)))
    except Exception:
        return 0
