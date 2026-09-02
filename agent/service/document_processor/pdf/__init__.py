"""`service.document_processor.pdf` 的包级公共导出。

对外只暴露一个函数 `convert_pdf_to_html`：把 PDF bytes 转成带 CSS 的完整
HTML 文档，内部完成 MinerU 执行与 HTML 渲染的组装，调用方无需自己串
converter / html 两个环节。
"""

from __future__ import annotations

from service.document_processor.pdf.converter import convert_pdf_bytes_to_content_list
from service.document_processor.pdf.html import build_html_from_content_list

__all__ = ["convert_pdf_to_html"]


def convert_pdf_to_html(source_bytes: bytes, filename: str) -> str:
    """PDF bytes -> 带 CSS 的完整 HTML 文档。

    实现步骤：

    ```text
    source_bytes + filename
      -> convert_pdf_bytes_to_content_list(...) 跑 MinerU pipeline
      -> build_html_from_content_list(...)      生成带 CSS 的完整 HTML
      -> 返回 html 字符串
    ```
    """

    content_list = convert_pdf_bytes_to_content_list(source_bytes, filename)
    return build_html_from_content_list(content_list)
