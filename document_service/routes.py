"""DocumentResourceService 的 protobuf 文件适配与异常映射。"""

import asyncio

import grpc
from agent_proto import agent_pb2 as pb
from agent_proto import agent_pb2_grpc
from document_service.document_resources import prepare_uploaded_resources
from document_service.document_resources.schemas import UploadedFile


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


class DocumentResourceService(agent_pb2_grpc.DocumentResourceServiceServicer):
    """独立 document service 的 gRPC 实现。"""

    async def PrepareResources(self, request, context):
        return await create_document_resource(request, context)
