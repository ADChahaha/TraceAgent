"""启动真实本机 gRPC Server，验证服务入口与协议生命周期。"""

import socket
import inspect
import subprocess
import sys
import threading
from pathlib import Path

import grpc
import pytest
from grpc_health.v1 import health_pb2, health_pb2_grpc

from agent_proto import agent_pb2 as pb, agent_pb2_grpc


def test_entrypoint_provides_grpc_server():
    import main

    assert callable(getattr(main, "create_server", None)), "agent 入口必须提供 gRPC server 工厂"
    assert inspect.iscoroutinefunction(main.create_server), "服务工厂必须异步初始化 grpc.aio 和 Health"
    assert not hasattr(main, "app"), "迁移后不再启动 FastAPI 应用"


def test_protocol_separates_document_resource_service():
    """文档准备 RPC 属于独立服务，AgentService 只保留问答流。"""
    assert "PrepareResources" not in pb.DESCRIPTOR.services_by_name["AgentService"].methods_by_name
    assert "ChatCompletion" in pb.DESCRIPTOR.services_by_name["AgentService"].methods_by_name
    assert "DocumentResourceService" in pb.DESCRIPTOR.services_by_name
    assert "PrepareResources" in pb.DESCRIPTOR.services_by_name["DocumentResourceService"].methods_by_name


def test_document_entrypoint_provides_separate_grpc_server():
    from document_service import main as document_main

    assert callable(getattr(document_main, "create_server", None))
    assert inspect.iscoroutinefunction(document_main.create_server)


def test_document_entrypoint_does_not_import_agent_route():
    source = Path(__file__).resolve().parents[3]
    result = subprocess.run([
        sys.executable,
        "-c",
        "import sys; import document_service.main; assert 'service.file_extraction_agent' not in sys.modules",
    ], cwd=source, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_health(rpc_channel):
    """标准 Health 可通过真实 RPC 读取。"""
    probe = health_pb2_grpc.HealthStub(rpc_channel)
    for service in ("", "traceagent.v1.AgentService"):
        assert probe.Check(health_pb2.HealthCheckRequest(service=service), timeout=2).status == health_pb2.HealthCheckResponse.SERVING


def test_agent_server_does_not_expose_document_rpc(rpc_channel):
    query = rpc_channel.unary_unary("/traceagent.v1.AgentService/PrepareResources")
    with pytest.raises(grpc.RpcError) as error:
        query(pb.PrepareResourcesRequest().SerializeToString(), timeout=2)
    assert error.value.code() == grpc.StatusCode.UNIMPLEMENTED


def test_document_health(document_rpc_channel):
    probe = health_pb2_grpc.HealthStub(document_rpc_channel)
    for service in ("", "traceagent.v1.DocumentResourceService"):
        assert probe.Check(health_pb2.HealthCheckRequest(service=service), timeout=2).status == health_pb2.HealthCheckResponse.SERVING


def test_capabilities_is_not_exposed(rpc, rpc_channel):
    """能力查询及其专用消息已移除，旧 RPC 路径不再注册。"""
    assert "GetCapabilities" not in pb.DESCRIPTOR.services_by_name["AgentService"].methods_by_name
    assert not hasattr(rpc, "GetCapabilities")
    assert "CapabilitiesResponse" not in pb.DESCRIPTOR.message_types_by_name
    assert "Empty" not in pb.DESCRIPTOR.message_types_by_name
    query = rpc_channel.unary_unary("/traceagent.v1.AgentService/GetCapabilities")
    with pytest.raises(grpc.RpcError) as error:
        query(b"", timeout=2)
    assert error.value.code() == grpc.StatusCode.UNIMPLEMENTED


def test_blocking_preparation_keeps_control_rpcs_responsive(monkeypatch, document_rpc_server_factory):
    """单线程执行器忙于文档解析时，事件循环仍可探活。"""
    from document_service.document_resources import application as document_resources
    started = threading.Event()
    release = threading.Event()

    def blocked(*args, **kwargs):
        from traceagent_shared.object_store import ResourceRef
        started.set()
        release.wait(5)
        return [ResourceRef(type="documents", location="s3://res_blocked/documents.zip")]

    monkeypatch.setattr(document_resources, "publish_resources", blocked)
    monkeypatch.setattr(document_resources.processor, "process",
                        lambda file: type("Document", (), {"filename": "a.docx", "html": "<p>a</p>"})())
    with document_rpc_server_factory(workers=1) as channel:
        stub = agent_pb2_grpc.DocumentResourceServiceStub(channel)
        pending = stub.PrepareResources.future(pb.PrepareResourcesRequest(
            session_id="blocked", files=[pb.UploadedFile(filename="a.docx", content=b"test")]), timeout=5)
        try:
            assert started.wait(2)
            assert health_pb2_grpc.HealthStub(channel).Check(
                health_pb2.HealthCheckRequest(), timeout=1).status == health_pb2.HealthCheckResponse.SERVING
        finally:
            release.set()
            pending.result(timeout=2)


def test_oversized_request_returns_resource_exhausted(document_rpc_server_factory):
    """超过配置的消息上限时由 gRPC 拒绝，不进入文档解析。"""
    with document_rpc_server_factory(max_message_bytes=1024) as channel:
        with pytest.raises(grpc.RpcError) as error:
            agent_pb2_grpc.DocumentResourceServiceStub(channel).PrepareResources(pb.PrepareResourcesRequest(
                files=[pb.UploadedFile(filename="large.pdf", content=b"x" * 2048)]), timeout=2)
        assert error.value.code() == grpc.StatusCode.RESOURCE_EXHAUSTED


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


def test_document_cli_starts_server_and_health_command():
    repository = Path(__file__).resolve().parents[3]
    with socket.socket() as available:
        available.bind(("127.0.0.1", 0))
        port = available.getsockname()[1]
    target = f"127.0.0.1:{port}"
    process = subprocess.Popen([sys.executable, "-m", "document_service.main", "--host", "127.0.0.1", "--port", str(port)],
                               cwd=repository, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        with grpc.insecure_channel(target) as channel:
            grpc.channel_ready_future(channel).result(timeout=10)
        result = subprocess.run([sys.executable, "-m", "document_service.main", "--check-health", target, "--timeout", "3"],
                                cwd=repository, capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, result.stderr
        assert "SERVING" in result.stdout
    finally:
        process.terminate()
        process.communicate(timeout=10)
