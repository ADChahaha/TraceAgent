"""创建 gRPC Server → 注册 agent 与标准探活服务 → 监听并等待退出。"""

from concurrent.futures import ThreadPoolExecutor
import argparse
import os
import signal
import threading

import grpc
from grpc_health.v1 import health, health_pb2, health_pb2_grpc

from agent_proto import agent_pb2_grpc
from routes import AgentService


def create_server(*, workers: int = 16, max_message_bytes: int = 64 * 1024 * 1024) -> grpc.Server:
    """配置消息上限，预留两个 worker 处理控制请求，注册业务与健康服务。"""
    if workers < 3 or max_message_bytes <= 0:
        raise ValueError("workers must be >= 3 and max_message_bytes must be positive")
    server = grpc.server(ThreadPoolExecutor(max_workers=workers), options=[
        ("grpc.max_receive_message_length", max_message_bytes),
        ("grpc.max_send_message_length", max_message_bytes),
    ])
    agent_pb2_grpc.add_AgentServiceServicer_to_server(AgentService(workers - 2), server)
    probe = health.HealthServicer()
    probe.set("", health_pb2.HealthCheckResponse.SERVING)
    probe.set("traceagent.v1.AgentService", health_pb2.HealthCheckResponse.SERVING)
    health_pb2_grpc.add_HealthServicer_to_server(probe, server)
    return server


def main() -> int:
    """CLI 参数/环境变量 → 启动服务或探活 → 信号触发停服；探活失败返回 1。"""
    parser = argparse.ArgumentParser(description="Agent gRPC service")
    parser.add_argument("--host", default=os.getenv("AGENT_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("AGENT_PORT", "8001")))
    parser.add_argument("--workers", type=int, default=int(os.getenv("AGENT_GRPC_WORKERS", "16")))
    parser.add_argument("--max-message-bytes", type=int,
                        default=int(os.getenv("AGENT_GRPC_MAX_MESSAGE_BYTES", str(64 * 1024 * 1024))))
    parser.add_argument("--check-health", metavar="HOST:PORT")
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()
    if args.check_health:
        try:
            with grpc.insecure_channel(args.check_health) as channel:
                result = health_pb2_grpc.HealthStub(channel).Check(
                    health_pb2.HealthCheckRequest(service="traceagent.v1.AgentService"), timeout=args.timeout)
            if result.status != health_pb2.HealthCheckResponse.SERVING:
                return 1
            print("SERVING")
            return 0
        except grpc.RpcError as exc:
            print(f"Health check failed: {exc.code().name}")
            return 1

    server = create_server(workers=args.workers, max_message_bytes=args.max_message_bytes)
    host = f"[{args.host}]" if ":" in args.host and not args.host.startswith("[") else args.host
    port = server.add_insecure_port(f"{host}:{args.port}")
    if not port:
        raise RuntimeError("gRPC server could not bind address")
    stopped = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stopped.set())
    server.start()
    print(f"Agent gRPC listening on {host}:{port}", flush=True)
    try:
        stopped.wait()
    finally:
        server.stop(5).wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
