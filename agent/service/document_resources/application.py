"""上传文件 → 批次校验 → PDF/DOCX 解析 → 资源构建发布；仅接收普通 Python 数据。

空批次和非法类型抛 ValueError；解析异常包装 RuntimeError，资源构建异常直接传播。
"""

from dataclasses import dataclass
from io import BytesIO
from typing import Any

from service.document_processor import processor
from service.document_resources.resources import prepare_resources
from service.document_resources.schemas import InputDocument, UploadedFile
from service.object_store import ResourceRef


@dataclass
class UploadFileProxy:
    filename: str
    file: Any

    def read(self, *args):
        return self.file.read(*args)

    def seek(self, *args):
        return self.file.seek(*args)


def prepare_uploaded_resources(files: list[UploadedFile]) -> list[ResourceRef]:
    """文件数据 → 全批次类型校验 → processor 解析 → prepare_resources 发布；解析失败补充文件名。"""
    if not files:
        raise ValueError("files must be non-empty")
    for file in files:
        processor.detect_file_type(file_type=None, filename=file.filename)
    documents = []
    raw_files = []
    for file in files:
        raw_files.append((file.filename, bytes(file.content)))
        with BytesIO(file.content) as content:
            try:
                result = processor.process(UploadFileProxy(file.filename, content))
            except Exception as exc:
                raise RuntimeError(f"document parsing failed for {file.filename}: {exc}") from exc
        documents.append(InputDocument(filename=result.filename, html=result.html))
    refs = prepare_resources(documents, raw_files=raw_files)
    return refs
