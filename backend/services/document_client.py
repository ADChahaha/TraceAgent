"""业务参数转换为 protobuf；只负责独立 document resource service。"""

import grpc

from agent_proto import agent_pb2 as pb, agent_pb2_grpc as rpc
from backend.services.errors import DocumentServiceError


class DocumentResourceClient:
    """调用文档资源服务准备或重建一个 session 的资源包。"""

    def __init__(self, *, target, timeout_seconds=1200.0, max_message_bytes=64 * 1024 * 1024):
        self.timeout_seconds = timeout_seconds
        self.channel = grpc.aio.insecure_channel(target, options=[
            ("grpc.max_send_message_length", max_message_bytes),
            ("grpc.max_receive_message_length", max_message_bytes),
        ])
        self.stub = rpc.DocumentResourceServiceStub(self.channel)

    async def prepare_resources(self, *, session_id, files, remove_raw=None):
        """把会话增删请求转成 PrepareResources，并返回资源定位数组。"""
        request = pb.PrepareResourcesRequest(
            session_id=session_id,
            files=[pb.UploadedFile(filename=f["filename"], content=f["content"]) for f in files],
            remove_raw=[pb.ResourceRef(type=ref["type"], location=ref["location"])
                        for ref in (remove_raw or [])],
        )
        try:
            response = await self.stub.PrepareResources(request, timeout=self.timeout_seconds)
        except grpc.RpcError as exc:
            raise DocumentServiceError(
                f"document service gRPC: {exc.code().name}: {exc.details()}"
            ) from exc
        return [{"type": ref.type, "location": ref.location} for ref in response.resource_path]

    async def close(self):
        await self.channel.close()
