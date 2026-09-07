"""启动真实本机 gRPC Server，验证服务入口与协议生命周期。"""

import socket
import subprocess
import sys
import threading
from pathlib import Path

import grpc
import pytest
from grpc_health.v1 import health_pb2, health_pb2_grpc

from agent_proto import agent_pb2 as pb, agent_pb2_grpc
from main import create_server


def test_entrypoint_provides_grpc_server():
    import main

    assert callable(getattr(main, "create_server", None)), "agent 入口必须提供 gRPC server 工厂"
    assert not hasattr(main, "app"), "迁移后不再启动 FastAPI 应用"


def test_health_and_capabilities(rpc, rpc_channel):
    """标准 Health 与能力查询均可通过真实 RPC 读取。"""
    probe = health_pb2_grpc.HealthStub(rpc_channel)
    for service in ("", "traceagent.v1.AgentService"):
        assert probe.Check(health_pb2.HealthCheckRequest(service=service), timeout=2).status == health_pb2.HealthCheckResponse.SERVING
    result = rpc.GetCapabilities(pb.Empty(), timeout=2)
    assert list(result.supported_file_types) == ["pdf", "docx"]
    assert list(result.implemented_file_types) == ["pdf", "docx"]


def test_busy_work_is_rejected_and_cancel_stays_available(monkeypatch):
    """长任务达到容量后快速拒绝新工作，保留线程处理取消和探活。"""
    from routes import document_resources
    started = threading.Event()
    release = threading.Event()
    def blocked(request, context):
        started.set()
        release.wait(5)
        return pb.PrepareResourcesResponse()
    monkeypatch.setattr(document_resources, "create_document_resource", blocked)
    server = create_server(workers=3)
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    try:
        with grpc.insecure_channel(f"127.0.0.1:{port}") as channel:
            stub = agent_pb2_grpc.AgentServiceStub(channel)
            pending = stub.PrepareResources.future(pb.PrepareResourcesRequest(), timeout=5)
            assert started.wait(2)
            try:
                with pytest.raises(grpc.RpcError) as error:
                    stub.PrepareResources(pb.PrepareResourcesRequest(), timeout=1)
                assert error.value.code() == grpc.StatusCode.RESOURCE_EXHAUSTED
                assert stub.CancelCompletion(pb.CompletionRequest(completion_id="missing"), timeout=1).status == "not_found"
            finally:
                release.set()
                pending.result(timeout=2)
    finally:
        release.set()
        server.stop(0).wait(5)


def test_oversized_request_returns_resource_exhausted():
    """超过配置的消息上限时由 gRPC 拒绝，不进入文档解析。"""
    server = create_server(max_message_bytes=1024)
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    try:
        with grpc.insecure_channel(f"127.0.0.1:{port}") as channel:
            with pytest.raises(grpc.RpcError) as error:
                agent_pb2_grpc.AgentServiceStub(channel).PrepareResources(pb.PrepareResourcesRequest(
                    files=[pb.UploadedFile(filename="large.pdf", content=b"x" * 2048)]), timeout=2)
            assert error.value.code() == grpc.StatusCode.RESOURCE_EXHAUSTED
    finally:
        server.stop(0).wait(5)


def test_cli_starts_server_and_health_command():
    """真实子进程启动服务，并用同一 CLI 探活，验证部署入口。"""
    entrypoint = Path(__file__).resolve().parents[2] / "main.py"
    with socket.socket() as available:
        available.bind(("127.0.0.1", 0))
        port = available.getsockname()[1]
    target = f"127.0.0.1:{port}"
    process = subprocess.Popen([sys.executable, str(entrypoint), "--host", "127.0.0.1", "--port", str(port)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        with grpc.insecure_channel(target) as channel:
            grpc.channel_ready_future(channel).result(timeout=10)
        result = subprocess.run([sys.executable, str(entrypoint), "--check-health", target, "--timeout", "3"],
                                capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, result.stderr
        assert "SERVING" in result.stdout
    finally:
        process.terminate()
        process.communicate(timeout=10)
