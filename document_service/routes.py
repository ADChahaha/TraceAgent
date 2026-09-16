import asyncio

import grpc
from agent_proto import agent_pb2 as pb
from agent_proto import agent_pb2_grpc
from document_service.document_resources import prepare_session_resources
from document_service.document_resources.reader import ArchiveNotFoundError, read_blocks
from document_service.document_resources.schemas import UploadedFile


async def create_document_resource(request, context):
    try:
        files = [UploadedFile(filename=file.filename, content=bytes(file.content)) for file in request.files]
        remove_raw = [{"type": ref.type, "location": ref.location} for ref in request.remove_raw]
        refs = await asyncio.to_thread(prepare_session_resources, request.session_id, files, remove_raw)
        return pb.PrepareResourcesResponse(
            resource_path=[pb.ResourceRef(type=ref.type, location=ref.location) for ref in refs],
        )
    except ValueError as exc:
        await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
    except Exception as exc:
        await context.abort(grpc.StatusCode.INTERNAL, f"document resource preparation failed: {exc}")


async def read_document_blocks(request, context):
    try:
        blocks = await asyncio.to_thread(read_blocks, request.bucket, list(request.keys))
        return pb.ReadBlocksResponse(
            blocks=[pb.BlockContent(key=block["key"], text=block["text"], found=block["found"]) for block in blocks]
        )
    except ArchiveNotFoundError as exc:
        await context.abort(grpc.StatusCode.NOT_FOUND, str(exc))
    except ValueError as exc:
        await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
    except Exception as exc:
        await context.abort(grpc.StatusCode.INTERNAL, f"document block read failed: {exc}")


class DocumentResourceService(agent_pb2_grpc.DocumentResourceServiceServicer):
    """独立 document service 的 gRPC 实现。"""

    async def PrepareResources(self, request, context):
        return await create_document_resource(request, context)

    async def ReadBlocks(self, request, context):
        return await read_document_blocks(request, context)
