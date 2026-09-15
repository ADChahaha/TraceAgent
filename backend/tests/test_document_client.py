"""独立 document service gRPC client 的请求映射和错误边界。"""

import asyncio

import grpc
import pytest

from agent_proto import agent_pb2 as pb, agent_pb2_grpc as rpc
from backend.services.document_client import DocumentResourceClient
from backend.services.errors import DocumentServiceError


def test_document_client_calls_document_resource_service():
    async def scenario():
        seen = {}

        class Service(rpc.DocumentResourceServiceServicer):
            async def PrepareResources(self, request, context):
                seen["request"] = request
                return pb.PrepareResourcesResponse(
                    resource_path=[pb.ResourceRef(type="documents", location="s3://res/documents.zip")]
                )

        server = grpc.aio.server()
        rpc.add_DocumentResourceServiceServicer_to_server(Service(), server)
        port = server.add_insecure_port("127.0.0.1:0")
        await server.start()
        client = DocumentResourceClient(target=f"127.0.0.1:{port}")
        try:
            refs = await client.prepare_resources(
                session_id="s1",
                files=[{"filename": "a.pdf", "content": b"pdf"}],
                remove_raw=[{"type": "raw", "location": "s3://res/raw/old.pdf"}],
            )
            assert refs == [{"type": "documents", "location": "s3://res/documents.zip"}]
            assert seen["request"].session_id == "s1"
            assert seen["request"].files[0].content == b"pdf"
            assert seen["request"].remove_raw[0].location.endswith("old.pdf")
        finally:
            await client.close()
            await server.stop(0)

    asyncio.run(scenario())


def test_document_client_maps_grpc_errors():
    async def scenario():
        class Service(rpc.DocumentResourceServiceServicer):
            async def PrepareResources(self, request, context):
                await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "bad document")

        server = grpc.aio.server()
        rpc.add_DocumentResourceServiceServicer_to_server(Service(), server)
        port = server.add_insecure_port("127.0.0.1:0")
        await server.start()
        client = DocumentResourceClient(target=f"127.0.0.1:{port}")
        try:
            with pytest.raises(DocumentServiceError, match="bad document"):
                await client.prepare_resources(session_id="s1", files=[])
        finally:
            await client.close()
            await server.stop(0)

    asyncio.run(scenario())
