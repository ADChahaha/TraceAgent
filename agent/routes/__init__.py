"""将 AgentService 的问答 RPC 连接到问答适配函数。"""

from contextlib import aclosing

from agent_proto import agent_pb2_grpc


class AgentService(agent_pb2_grpc.AgentServiceServicer):
    async def ChatCompletion(self, request, context):
        # 延迟导入让 document service 加载资源 route 时不引入问答模型依赖。
        from routes import file_extraction_agent

        async with aclosing(
            file_extraction_agent.create_chat_completion(request, context)
        ) as stream:
            async for event in stream:
                yield event
