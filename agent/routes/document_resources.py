"""protobuf 文件 → UploadedFile → 在线程中调用上传业务入口 → protobuf，异常映射 gRPC 状态。"""

import asyncio

import grpc
from agent_proto import agent_pb2 as pb
from service.document_resources import prepare_uploaded_resources
from service.document_resources.schemas import UploadedFile


async def create_document_resource(request, context):
    try:
        files = [UploadedFile(filename=file.filename, content=bytes(file.content)) for file in request.files]
        refs = await asyncio.to_thread(prepare_uploaded_resources, files)
        return pb.PrepareResourcesResponse(
            resource_path=[pb.ResourceRef(type=ref.type, location=ref.location) for ref in refs],
        )
    except ValueError as exc:
        await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
    except Exception as exc:
        await context.abort(grpc.StatusCode.INTERNAL, f"document resource preparation failed: {exc}")
