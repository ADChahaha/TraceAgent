"""业务参数转换为 protobuf；资源调用与 completion 流均走独立 agent 的 gRPC。"""

import grpc
from google.protobuf.json_format import MessageToDict

from agent_proto import agent_pb2 as pb, agent_pb2_grpc as rpc
from backend.services.errors import AgentServiceError


class CompletionCall:
    """保留原始 call 的取消能力，同时把流事件转换为普通字典。"""

    def __init__(self, call):
        self.call = call
        self.iterator = call.__aiter__()

    def cancel(self):
        return self.call.cancel()

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            event = await self.iterator.__anext__()
        except grpc.RpcError as exc:
            raise AgentServiceError(f"agent gRPC: {exc.code().name}: {exc.details()}") from exc
        result = MessageToDict(event, preserving_proto_field_name=True)
        result["seq"] = event.seq
        result.setdefault("tool_calls", [])
        return result


class AgentClient:
    def __init__(self, *, target, timeout_seconds=1200.0, max_message_bytes=64 * 1024 * 1024):
        self.timeout_seconds = timeout_seconds
        self.channel = grpc.aio.insecure_channel(target, options=[
            ("grpc.max_send_message_length", max_message_bytes),
            ("grpc.max_receive_message_length", max_message_bytes),
        ])
        self.stub = rpc.AgentServiceStub(self.channel)

    async def prepare_resources(self, files):
        request = pb.PrepareResourcesRequest(files=[pb.UploadedFile(filename=f["filename"], content=f["content"]) for f in files])
        try:
            response = await self.stub.PrepareResources(request, timeout=self.timeout_seconds)
        except grpc.RpcError as exc:
            raise AgentServiceError(f"agent gRPC: {exc.code().name}: {exc.details()}") from exc
        return [{"type": ref.type, "location": ref.location} for ref in response.resource_path]

    def chat_completion(self, *, completion_id, resource_path, messages, run_options=None):
        request = pb.ChatCompletionRequest(
            completion_id=completion_id,
            resource_path=[pb.ResourceRef(**ref) for ref in resource_path],
            messages=[pb.QaMessage(**message) for message in messages],
            run_options=pb.RunOptions(**(run_options or {})),
        )
        return CompletionCall(self.stub.ChatCompletion(request, timeout=self.timeout_seconds))

    async def close(self):
        await self.channel.close()
