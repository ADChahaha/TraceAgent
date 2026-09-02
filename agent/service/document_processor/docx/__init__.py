"""`service.document_processor.docx` 的包级公共导出。

对外只暴露一个函数 `convert_docx_to_html`：把 DOCX bytes 转成带 CSS 的完整
HTML 文档，内部用 python-docx 按 Word body 原始顺序解析。
"""

from __future__ import annotations

from service.document_processor.docx.docx_processor import convert_docx_to_html

__all__ = ["convert_docx_to_html"]
