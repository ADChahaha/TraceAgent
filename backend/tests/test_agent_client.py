"""本机真实 gRPC 服务验证 protobuf 映射、资源传输和原 call 取消。"""

import asyncio
import io
import zipfile

import grpc
import pytest

from agent_proto import agent_pb2 as pb, agent_pb2_grpc as rpc
from backend.services.agent_client import AgentClient
from backend.services.errors import AgentServiceError


def test_grpc_resources_messages_and_original_call_cancellation():
    async def scenario():
        seen = {}
        stopped = asyncio.Event()
        class Service(rpc.AgentServiceServicer):
            async def PrepareResources(self, request, context):
                seen["file"] = request.files[0]
                return pb.PrepareResourcesResponse(resource_path=[pb.ResourceRef(type="documents", location="s3://test/documents.zip")])

            async def ChatCompletion(self, request, context):
                seen["request"] = request
                try:
                    yield pb.CompletionEvent(type="model_message.delta", seq=1, message_id="m", delta="你好")
                    await asyncio.Event().wait()
                finally:
                    stopped.set()

        server = grpc.aio.server()
        rpc.add_AgentServiceServicer_to_server(Service(), server)
        port = server.add_insecure_port("127.0.0.1:0")
        await server.start()
        client = AgentClient(target=f"127.0.0.1:{port}")
        try:
            # 有实际正文的最小 DOCX 归档，验证传输不会改写文件 bytes。
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as archive:
                archive.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
                archive.writestr("_rels/.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
                archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>合同样本</w:t></w:r></w:p></w:body></w:document>')
            refs = await client.prepare_resources([{"filename": "sample.docx", "content": buffer.getvalue()}])
            assert refs == [{"type": "documents", "location": "s3://test/documents.zip"}]
            assert seen["file"].content == buffer.getvalue()
            call = client.chat_completion(completion_id="cmp_1", resource_path=refs,
                messages=[{"role": "tool", "content": "{}", "tool_call_id": "c", "name": "read"}],
                run_options={"tool_execution_timeout": 12})
            event = await anext(call)
            assert event["delta"] == "你好" and event["seq"] == 1
            assert seen["request"].messages[0].tool_call_id == "c"
            assert seen["request"].run_options.tool_execution_timeout == 12
            call.cancel()
            await asyncio.wait_for(stopped.wait(), 2)
        finally:
            await client.close()
            await server.stop(0)
    asyncio.run(scenario())


def test_grpc_failure_maps_to_agent_service_error():
    async def scenario():
        class Service(rpc.AgentServiceServicer):
            async def PrepareResources(self, request, context):
                await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "bad resource")
        server = grpc.aio.server()
        rpc.add_AgentServiceServicer_to_server(Service(), server)
        port = server.add_insecure_port("127.0.0.1:0")
        await server.start()
        client = AgentClient(target=f"127.0.0.1:{port}")
        try:
            with pytest.raises(AgentServiceError, match="bad resource"):
                await client.prepare_resources([])
        finally:
            await client.close()
            await server.stop(0)
    asyncio.run(scenario())
