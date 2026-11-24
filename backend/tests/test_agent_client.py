"""本机真实 gRPC 服务验证 agent completion protobuf 映射和原 call 取消。"""

import asyncio
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
            call = client.chat_completion(completion_id="cmp_1", resource_path=[
                    {"type": "documents", "location": "s3://test/documents.zip"}],
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
            async def ChatCompletion(self, request, context):
                await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "bad resource")
        server = grpc.aio.server()
        rpc.add_AgentServiceServicer_to_server(Service(), server)
        port = server.add_insecure_port("127.0.0.1:0")
        await server.start()
        client = AgentClient(target=f"127.0.0.1:{port}")
        try:
            with pytest.raises(AgentServiceError, match="bad resource"):
                await anext(client.chat_completion(
                    completion_id="cmp", resource_path=[], messages=[{"role": "user", "content": "问题"}]
                ))
        finally:
            await client.close()
            await server.stop(0)
    asyncio.run(scenario())


def test_grpc_generate_title_roundtrip_and_error_mapping():
    async def scenario():
        seen = {}

        class Service(rpc.AgentServiceServicer):
            async def GenerateTitle(self, request, context):
                seen["question"] = request.question
                seen["filenames"] = list(request.filenames)
                if request.question == "fail":
                    await context.abort(grpc.StatusCode.INTERNAL, "model down")
                return pb.GenerateTitleResponse(title="合同付款周期摘要")

        server = grpc.aio.server()
        rpc.add_AgentServiceServicer_to_server(Service(), server)
        port = server.add_insecure_port("127.0.0.1:0")
        await server.start()
        client = AgentClient(target=f"127.0.0.1:{port}")
        try:
            title = await client.generate_title(
                question="合同里的付款周期是什么？",
                filenames=["contract.pdf"],
                timeout_seconds=5.0,
            )
            assert title == "合同付款周期摘要"
            assert seen == {"question": "合同里的付款周期是什么？", "filenames": ["contract.pdf"]}
            with pytest.raises(AgentServiceError, match="model down"):
                await client.generate_title(question="fail", timeout_seconds=5.0)
        finally:
            await client.close()
            await server.stop(0)

    asyncio.run(scenario())
