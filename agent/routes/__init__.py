"""将生成的 AgentService 方法连接到资源与问答适配函数。"""

from agent_proto import agent_pb2_grpc
from routes import document_resources, file_extraction_agent


class AgentService(agent_pb2_grpc.AgentServiceServicer):
    async def PrepareResources(self, request, context):
        return await document_resources.create_document_resource(request, context)

    async def ChatCompletion(self, request, context):
        stream = file_extraction_agent.create_chat_completion(request, context)
        try:
            async for event in stream:
                yield event
        finally:
            await stream.aclose()

    async def CancelCompletion(self, request, context):
        return await file_extraction_agent.cancel_chat_completion(request, context)
