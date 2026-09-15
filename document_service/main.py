"""创建并启动独立的 document resource gRPC 服务。"""

from concurrent.futures import ThreadPoolExecutor
import argparse
import asyncio
import os
import signal

import grpc
from grpc_health.v1 import health, health_pb2, health_pb2_grpc

from agent_proto import agent_pb2_grpc
from document_service.routes import DocumentResourceService


async def create_server(*, max_message_bytes: int = 64 * 1024 * 1024) -> grpc.aio.Server:
    """创建只注册文档资源 RPC 的 gRPC server。"""
    if max_message_bytes <= 0:
        raise ValueError("max_message_bytes must be positive")
    server = grpc.aio.server(options=[
        ("grpc.max_receive_message_length", max_message_bytes),
        ("grpc.max_send_message_length", max_message_bytes),
    ])
    agent_pb2_grpc.add_DocumentResourceServiceServicer_to_server(DocumentResourceService(), server)
    probe = health.aio.HealthServicer()
    await probe.set("", health_pb2.HealthCheckResponse.SERVING)
    await probe.set("traceagent.v1.DocumentResourceService", health_pb2.HealthCheckResponse.SERVING)
    health_pb2_grpc.add_HealthServicer_to_server(probe, server)
    return server


def main() -> int:
    """CLI 参数/环境变量 → 启动 document service 或执行标准探活。"""
    parser = argparse.ArgumentParser(description="Document resource gRPC service")
    parser.add_argument("--host", default=os.getenv("DOCUMENT_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("DOCUMENT_PORT", "8002")))
    parser.add_argument("--workers", type=int, default=int(os.getenv("DOCUMENT_GRPC_WORKERS", "16")))
    parser.add_argument("--max-message-bytes", type=int,
                        default=int(os.getenv("DOCUMENT_GRPC_MAX_MESSAGE_BYTES", str(64 * 1024 * 1024))))
    parser.add_argument("--check-health", metavar="HOST:PORT")
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    return asyncio.run(run(args))


async def run(args) -> int:
    """启动服务，或探活后返回适合 shell 使用的退出码。"""
    if args.check_health:
        try:
            async with grpc.aio.insecure_channel(args.check_health) as channel:
                result = await health_pb2_grpc.HealthStub(channel).Check(
                    health_pb2.HealthCheckRequest(service="traceagent.v1.DocumentResourceService"),
                    timeout=args.timeout,
                )
            if result.status != health_pb2.HealthCheckResponse.SERVING:
                return 1
            print("SERVING")
            return 0
        except grpc.RpcError as exc:
            print(f"Health check failed: {exc.code().name}")
            return 1

    loop = asyncio.get_running_loop()
    loop.set_default_executor(ThreadPoolExecutor(max_workers=args.workers, thread_name_prefix="document-blocking"))
    server = await create_server(max_message_bytes=args.max_message_bytes)
    host = f"[{args.host}]" if ":" in args.host and not args.host.startswith("[") else args.host
    port = server.add_insecure_port(f"{host}:{args.port}")
    if not port:
        raise RuntimeError("gRPC server could not bind address")
    stopped = asyncio.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: loop.call_soon_threadsafe(stopped.set))
    await server.start()
    print(f"Document resource gRPC listening on {host}:{port}", flush=True)
    try:
        await stopped.wait()
    finally:
        await server.stop(5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
