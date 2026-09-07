"""上传 bytes → 校验文件类型 → processor.process → prepare_resources → protobuf 响应。

PDF/DOCX 解析和资源构建通过 asyncio.to_thread 执行，不阻塞事件循环。输入错误映射
INVALID_ARGUMENT；解析与构建异常映射 INTERNAL，原资源发布逻辑负责清理半成品。
"""

import asyncio
from dataclasses import dataclass
from io import BytesIO
from typing import Any

import grpc

from agent_proto import agent_pb2 as pb
from service.document_processor import processor
from service.document_resources import prepare_resources
from service.document_resources.schemas import InputDocument


@dataclass
class UploadFileProxy:
    filename: str
    file: Any

    def read(self, *args):
        return self.file.read(*args)

    def seek(self, *args):
        return self.file.seek(*args)


async def create_document_resource(request, context):
    try:
        return await asyncio.to_thread(_prepare, request)
    except (processor.InvalidFileObjectError, processor.UnsupportedFileTypeError, ValueError) as exc:
        await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
    except Exception as exc:
        await context.abort(grpc.StatusCode.INTERNAL, f"document resource preparation failed: {exc}")


def _prepare(request):
    """阻塞工作只接收请求数据，不在线程中访问 aio context。"""
    if not request.files:
        raise ValueError("files must be non-empty")
    for file in request.files:
        processor.detect_file_type(file_type=None, filename=file.filename)
    documents = []
    for file in request.files:
        with BytesIO(file.content) as content:
            try:
                result = processor.process(UploadFileProxy(file.filename, content))
            except Exception as exc:
                raise RuntimeError(f"document parsing failed for {file.filename}: {exc}") from exc
        documents.append(InputDocument(filename=result.filename, html=result.html))
    path = prepare_resources(documents)
    return pb.PrepareResourcesResponse(
        resource_path=path,
        documents=[pb.Document(filename=doc.filename, html=doc.html) for doc in documents],
    )
