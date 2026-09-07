"""将生成的 AgentService 方法连接到资源与问答适配函数。"""

from contextlib import contextmanager
from threading import BoundedSemaphore

import grpc

from agent_proto import agent_pb2_grpc
from routes import document_resources, file_extraction_agent


class AgentService(agent_pb2_grpc.AgentServiceServicer):
    def __init__(self, work_capacity: int = 14):
        self._slots = BoundedSemaphore(work_capacity)

    @contextmanager
    def _work_slot(self, context):
        """长任务不等待空闲槽，给取消和探活预留 worker。"""
        if not self._slots.acquire(blocking=False):
            context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, "agent work capacity reached")
        try:
            yield
        finally:
            self._slots.release()

    def PrepareResources(self, request, context):
        with self._work_slot(context):
            return document_resources.create_document_resource(request, context)

    def ChatCompletion(self, request, context):
        with self._work_slot(context):
            yield from file_extraction_agent.create_chat_completion(request, context)

    def CancelCompletion(self, request, context):
        return file_extraction_agent.cancel_chat_completion(request, context)

    def GetCompletion(self, request, context):
        return file_extraction_agent.get_chat_completion(request, context)

    def GetCapabilities(self, request, context):
        return document_resources.capabilities(request, context)
