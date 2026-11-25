"""document_service gRPC 路由层：只依赖抽象协议与注入的对象存储工厂。"""

from __future__ import annotations

import asyncio

import grpc
from agent_proto import agent_pb2 as pb
from agent_proto import agent_pb2_grpc
from document_service.document_resources import prepare_session_resources
from document_service.document_resources.protocols import ObjectStoreFactory
from document_service.document_resources.reader import ArchiveNotFoundError, read_blocks
from document_service.document_resources.schemas import UploadedFile


async def create_document_resource(request, context, *, store_factory: ObjectStoreFactory):
    try:
        files = [UploadedFile(filename=file.filename, content=bytes(file.content)) for file in request.files]
        remove_raw = [{"type": ref.type, "location": ref.location} for ref in request.remove_raw]
        refs = await asyncio.to_thread(
            lambda: prepare_session_resources(
                request.session_id,
                files,
                remove_raw,
                store=store_factory(),
            )
        )
        return pb.PrepareResourcesResponse(
            resource_path=[pb.ResourceRef(type=ref.type, location=ref.location) for ref in refs],
        )
    except ValueError as exc:
        await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
    except Exception as exc:
        await context.abort(grpc.StatusCode.INTERNAL, f"document resource preparation failed: {exc}")


async def read_document_blocks(request, context, *, store_factory: ObjectStoreFactory):
    try:
        if not request.bucket:
            raise ValueError("bucket is required")
        keys = list(request.keys)
        if not keys:
            raise ValueError("keys are required")
        blocks = await asyncio.to_thread(
            lambda: read_blocks(request.bucket, keys, store=store_factory())
        )
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
    """独立 document service 的 gRPC 实现，由装配根注入对象存储工厂。"""

    def __init__(self, *, store_factory: ObjectStoreFactory):
        self._store_factory = store_factory

    async def PrepareResources(self, request, context):
        return await create_document_resource(request, context, store_factory=self._store_factory)

    async def ReadBlocks(self, request, context):
        return await read_document_blocks(request, context, store_factory=self._store_factory)
