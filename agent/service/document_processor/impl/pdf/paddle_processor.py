"""基于 PaddleOCR 的 PDF 处理器。

实现步骤：

```text
调用方把 pdf file_obj 交给 `PdfPaddleProcessor.process(...)`
  -> 继承 `PdfProcessor` 的文件名解析和二进制读取 helper，但不初始化 docling
  -> 用 pypdfium2 将 PDF 每一页渲染成图片
  -> 将页面图片逐页交给 PaddleOCR PPStructureV3
  -> 优先从结构化结果读取 markdown_texts 和 parsing_res_list
  -> 把表格块转成 `ContentBlock(kind="table")`，普通文字转成 `ContentBlock(kind="text")`
  -> 只有运行时返回普通 OCR 行时，才降级成 `ContentBlock(kind="text_line")`
  -> 按页拼接 markdown / md_list，并返回统一 `ProcessResult`
```
"""

from __future__ import annotations

from html.parser import HTMLParser
import os
import re
from io import BytesIO
from pathlib import Path
from typing import Any

from service.document_processor.impl.pdf.processor import (
    PdfProcessor,
    _package_models_root,
)
from service.document_processor.schemas import BoundingBox, ContentBlock, ProcessResult


class PdfPaddleProcessor(PdfProcessor):
    """不依赖 docling、直接用 PaddleOCR 识别 PDF 页面图片。"""

    def __init__(self, *, ocr_client: Any | None = None, render_scale: float = 2.0) -> None:
        self._ocr_client = (
            ocr_client if ocr_client is not None else self._build_ocr_client()
        )
        self._render_scale = render_scale

    def _process(self, file_obj):
        filename = self._resolve_filename(file_obj)
        source_bytes = self._read_source_bytes(file_obj)

        all_blocks: list[ContentBlock] = []
        page_markdown: list[str] = []
        for page_index, page_image in enumerate(
            self._render_pdf_pages(source_bytes),
            start=1,
        ):
            page_result = self._normalize_page_result(
                self._run_ocr(page_image),
                page_index=page_index,
            )
            all_blocks.extend(page_result["blocks"])
            page_markdown.append(page_result["markdown"])

        markdown = "\n\n".join(text for text in page_markdown if text)
        return ProcessResult(
            file_type=self.file_type.value,
            filename=filename,
            md_list=[text for text in page_markdown if text],
            markdown=markdown,
            blocks=all_blocks,
            meta_info={
                "ocr_engine": "paddleocr",
                "paddle_pipeline": "PPStructureV3",
                "block_count": len(all_blocks),
                "page_count": len(page_markdown),
                "render_scale": self._render_scale,
            },
        )

    def _render_pdf_pages(self, source_bytes: bytes) -> list[Any]:
        try:
            import pypdfium2 as pdfium
        except ImportError as exc:
            raise RuntimeError(
                "PdfPaddleProcessor requires pypdfium2 to render PDF pages."
            ) from exc

        pdf = pdfium.PdfDocument(BytesIO(source_bytes))
        images: list[Any] = []
        for page in pdf:
            bitmap = page.render(scale=self._render_scale)
            images.append(bitmap.to_pil())
        return images

    def _run_ocr(self, image: Any) -> Any:
        predict_method = getattr(self._ocr_client, "predict", None)
        if callable(predict_method):
            try:
                return predict_method(
                    self._to_ocr_input(image),
                    use_table_recognition=True,
                    format_block_content=True,
                )
            except TypeError:
                return predict_method(self._to_ocr_input(image))

        ocr_method = getattr(self._ocr_client, "ocr", None)
        if callable(ocr_method):
            return ocr_method(self._to_ocr_input(image), cls=True)

        raise RuntimeError("PaddleOCR client must provide ocr(...) or predict(...).")

    @staticmethod
    def _to_ocr_input(image: Any) -> Any:
        convert = getattr(image, "convert", None)
        if not callable(convert):
            return image

        try:
            import numpy as np
        except ImportError:
            return image

        image = convert("RGB")
        return np.asarray(image)

    @staticmethod
    def _build_ocr_client() -> Any:
        _configure_paddle_runtime_cache_dirs()
        try:
            from paddleocr import PPStructureV3
        except ImportError as exc:
            raise RuntimeError(
                "PdfPaddleProcessor requires paddleocr with PPStructureV3. "
                "Install the agent paddle extra before using "
                "DOCUMENT_PROCESSOR_PDF_ENGINE=pdf-paddle."
            ) from exc

        return PPStructureV3(
            lang="ch",
            ocr_version=os.getenv("DOCUMENT_PROCESSOR_PADDLE_OCR_VERSION", "PP-OCRv4"),
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            use_table_recognition=True,
            format_block_content=True,
        )

    def _normalize_page_result(
        self,
        raw_result: Any,
        *,
        page_index: int,
    ) -> dict[str, Any]:
        structure_result = self._normalize_structure_result(
            raw_result,
            page_index=page_index,
        )
        if structure_result is not None:
            return structure_result

        lines = self._normalize_ocr_result(raw_result)
        lines.sort(key=self._line_sort_key)
        blocks: list[ContentBlock] = []
        page_texts: list[str] = []
        for line in lines:
            page_texts.append(line["text"])
            blocks.append(
                ContentBlock(
                    text=line["text"],
                    page_no=page_index,
                    bbox=line["bbox"],
                    kind="text_line",
                    meta_info={
                        "ocr_engine": "paddleocr",
                        "paddle_pipeline": "PPStructureV3",
                        "score": line["score"],
                        "render_scale": self._render_scale,
                    },
                )
            )
        return {"markdown": "\n".join(page_texts), "blocks": blocks}

    def _normalize_structure_result(
        self,
        raw_result: Any,
        *,
        page_index: int,
    ) -> dict[str, Any] | None:
        for result in _iter_result_items(raw_result):
            parsing_blocks = _extract_parsing_blocks(result)
            markdown = _extract_markdown(result)
            if not parsing_blocks and not markdown:
                continue

            blocks = [
                block
                for block in (
                    self._content_block_from_parsing_block(
                        parsing_block,
                        page_index=page_index,
                    )
                    for parsing_block in parsing_blocks
                )
                if block is not None
            ]
            if not markdown:
                markdown = "\n\n".join(block.text for block in blocks if block.text)
            return {"markdown": markdown, "blocks": blocks}
        return None

    def _content_block_from_parsing_block(
        self,
        parsing_block: Any,
        *,
        page_index: int,
    ) -> ContentBlock | None:
        label = str(_value_for_key(parsing_block, "block_label", "label") or "").strip()
        content = str(
            _value_for_key(parsing_block, "block_content", "content") or ""
        ).strip()
        if not content:
            return None

        kind = "table" if label == "table" else "text"
        if kind == "table":
            content = _html_tables_to_markdown(content).strip()

        return ContentBlock(
            text=content,
            page_no=page_index,
            bbox=self._bbox_from_points(
                _value_for_key(parsing_block, "block_bbox", "bbox")
            ),
            kind=kind,
            meta_info={
                "ocr_engine": "paddleocr",
                "paddle_pipeline": "PPStructureV3",
                "block_label": label,
                "block_id": _value_for_key(parsing_block, "block_id", "id"),
                "block_order": _value_for_key(
                    parsing_block,
                    "block_order",
                    "order_index",
                ),
                "render_scale": self._render_scale,
            },
        )

    @classmethod
    def _normalize_ocr_result(cls, raw_result: Any) -> list[dict[str, Any]]:
        if raw_result is None:
            return []

        if isinstance(raw_result, dict):
            return cls._normalize_predict_dict(raw_result)

        if (
            isinstance(raw_result, list)
            and len(raw_result) == 1
            and isinstance(raw_result[0], dict)
        ):
            return cls._normalize_predict_dict(raw_result[0])

        candidate_lines = raw_result
        if (
            isinstance(raw_result, list)
            and len(raw_result) == 1
            and isinstance(raw_result[0], list)
        ):
            candidate_lines = raw_result[0]

        lines: list[dict[str, Any]] = []
        for item in candidate_lines or []:
            normalized = cls._normalize_ocr_line(item)
            if normalized is not None:
                lines.append(normalized)
        return lines

    @classmethod
    def _normalize_predict_dict(cls, result: dict[str, Any]) -> list[dict[str, Any]]:
        texts = result.get("rec_texts") or result.get("texts") or []
        scores = result.get("rec_scores") or result.get("scores") or []
        boxes = (
            result.get("rec_polys")
            or result.get("rec_boxes")
            or result.get("boxes")
            or []
        )
        lines: list[dict[str, Any]] = []
        for index, text in enumerate(texts):
            if not isinstance(text, str) or not text.strip():
                continue
            score = float(scores[index]) if index < len(scores) else None
            box = boxes[index] if index < len(boxes) else None
            lines.append(
                {
                    "text": text.strip(),
                    "score": score,
                    "bbox": cls._bbox_from_points(box),
                }
            )
        return lines

    @classmethod
    def _normalize_ocr_line(cls, item: Any) -> dict[str, Any] | None:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            return None

        box = item[0]
        text_payload = item[1]
        text: str | None = None
        score: float | None = None
        if isinstance(text_payload, (list, tuple)) and text_payload:
            if isinstance(text_payload[0], str):
                text = text_payload[0].strip()
            if len(text_payload) > 1 and text_payload[1] is not None:
                score = float(text_payload[1])
        elif isinstance(text_payload, str):
            text = text_payload.strip()

        if not text:
            return None
        return {
            "text": text,
            "score": score,
            "bbox": cls._bbox_from_points(box),
        }

    @staticmethod
    def _bbox_from_points(points: Any) -> BoundingBox | None:
        if points is None:
            return None

        try:
            if len(points) == 4 and all(
                isinstance(value, (int, float)) for value in points
            ):
                x0, y0, x1, y1 = points
                return BoundingBox(float(x0), float(y0), float(x1), float(y1))

            xs = [float(point[0]) for point in points]
            ys = [float(point[1]) for point in points]
            return BoundingBox(min(xs), min(ys), max(xs), max(ys))
        except (TypeError, ValueError, IndexError):
            return None

    @staticmethod
    def _line_sort_key(line: dict[str, Any]) -> tuple[float, float]:
        bbox = line["bbox"]
        if bbox is None:
            return (0.0, 0.0)
        return (bbox.y0, bbox.x0)


def _configure_paddle_runtime_cache_dirs() -> None:
    cache_root = _package_models_root() / "paddlex"

    if "PADDLE_PDX_CACHE_HOME" not in os.environ:
        os.environ["PADDLE_PDX_CACHE_HOME"] = str(cache_root)

    Path(os.environ["PADDLE_PDX_CACHE_HOME"]).mkdir(parents=True, exist_ok=True)


def _iter_result_items(raw_result: Any) -> list[Any]:
    if raw_result is None:
        return []
    if isinstance(raw_result, list):
        return raw_result
    return [raw_result]


def _extract_markdown(result: Any) -> str:
    to_markdown = getattr(result, "_to_markdown", None)
    if callable(to_markdown):
        try:
            markdown_data = to_markdown(pretty=False)
        except TypeError:
            markdown_data = to_markdown()
    else:
        markdown_data = _value_for_key(result, "markdown")
    markdown_text = _markdown_text_from_data(markdown_data)
    return _html_tables_to_markdown(markdown_text).strip()


def _markdown_text_from_data(markdown_data: Any) -> str:
    if markdown_data is None:
        return ""
    if isinstance(markdown_data, str):
        return markdown_data
    if isinstance(markdown_data, dict):
        return str(markdown_data.get("markdown_texts") or markdown_data.get("text") or "")
    return ""


def _extract_parsing_blocks(result: Any) -> list[Any]:
    json_payload = _value_for_key(result, "json")
    if isinstance(json_payload, dict):
        payload = json_payload.get("res", json_payload)
        blocks = payload.get("parsing_res_list")
        if isinstance(blocks, list):
            return blocks

    blocks = _value_for_key(result, "parsing_res_list")
    if isinstance(blocks, list):
        return blocks
    return []


def _value_for_key(value: Any, *keys: str) -> Any:
    for key in keys:
        if isinstance(value, dict) and key in value:
            return value[key]
        if hasattr(value, key):
            return getattr(value, key)
    return None


def _html_tables_to_markdown(text: str) -> str:
    if not text:
        return ""
    return re.sub(
        r"<table\b.*?</table>",
        lambda match: _html_table_to_markdown(match.group(0)),
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )


def _html_table_to_markdown(table_html: str) -> str:
    parser = _TableMarkdownParser()
    parser.feed(table_html)
    if not parser.rows:
        return table_html
    rows = [
        [cell.strip() for cell in row]
        for row in parser.rows
        if any(cell.strip() for cell in row)
    ]
    if not rows:
        return ""

    column_count = max(len(row) for row in rows)
    normalized_rows = [row + [""] * (column_count - len(row)) for row in rows]
    header = normalized_rows[0]
    data_rows = normalized_rows[1:]
    lines = [
        "| " + " | ".join(_escape_markdown_cell(cell) for cell in header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    lines.extend(
        "| " + " | ".join(_escape_markdown_cell(cell) for cell in row) + " |"
        for row in data_rows
    )
    return "\n".join(lines)


def _escape_markdown_cell(cell: str) -> str:
    return cell.replace("|", "\\|")


class _TableMarkdownParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        tag = tag.lower()
        if tag == "tr":
            self._current_row = []
        if tag in {"td", "th"}:
            self._current_cell = []

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self._current_cell is not None:
            if self._current_row is not None:
                self._current_row.append("".join(self._current_cell).strip())
            self._current_cell = None
        if tag == "tr" and self._current_row is not None:
            self.rows.append(self._current_row)
            self._current_row = None
