"""为接口测试启动真实本机 gRPC Server，测试后关闭 channel 和 server。"""

import grpc
import pytest

from agent_proto import agent_pb2_grpc
from main import create_server


@pytest.fixture
def rpc_channel():
    server = create_server()
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    channel = grpc.insecure_channel(f"127.0.0.1:{port}", options=[
        ("grpc.max_receive_message_length", 64 * 1024 * 1024),
        ("grpc.max_send_message_length", 64 * 1024 * 1024),
    ])
    try:
        grpc.channel_ready_future(channel).result(timeout=5)
        yield channel
    finally:
        channel.close()
        server.stop(0).wait(5)


@pytest.fixture
def rpc(rpc_channel):
    return agent_pb2_grpc.AgentServiceStub(rpc_channel)
