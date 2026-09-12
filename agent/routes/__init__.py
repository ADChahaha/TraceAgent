"""将生成的 AgentService 方法连接到资源与问答适配函数。"""

from contextlib import aclosing

from agent_proto import agent_pb2_grpc
from routes import document_resources, file_extraction_agent


class AgentService(agent_pb2_grpc.AgentServiceServicer):
    async def PrepareResources(self, request, context):
        return await document_resources.create_document_resource(request, context)

    async def ChatCompletion(self, request, context):
        async with aclosing(
            file_extraction_agent.create_chat_completion(request, context)
        ) as stream:
            async for event in stream:
                yield event
