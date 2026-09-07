"""为接口测试启动真实本机 gRPC Server，测试后关闭 channel 和 server。"""

import asyncio
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
import threading

import grpc
import pytest

from agent_proto import agent_pb2_grpc
from main import create_server


@pytest.fixture
def rpc_server_factory():
    @contextmanager
    def running(*, workers=16, **options):
        ready = Future()

        async def serve():
            loop = asyncio.get_running_loop()
            loop.set_default_executor(ThreadPoolExecutor(max_workers=workers))
            stopped = asyncio.Event()
            server = await create_server(**options)
            port = server.add_insecure_port("127.0.0.1:0")
            await server.start()
            ready.set_result((port, loop, stopped))
            try:
                await stopped.wait()
            finally:
                await server.stop(0)

        def run():
            try:
                asyncio.run(serve())
            except BaseException as exc:
                if not ready.done():
                    ready.set_exception(exc)
                else:
                    raise

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        port, loop, stopped = ready.result(timeout=10)
        channel = grpc.insecure_channel(f"127.0.0.1:{port}", options=[
            ("grpc.max_receive_message_length", 64 * 1024 * 1024),
            ("grpc.max_send_message_length", 64 * 1024 * 1024),
        ])
        try:
            grpc.channel_ready_future(channel).result(timeout=5)
            yield channel
        finally:
            channel.close()
            loop.call_soon_threadsafe(stopped.set)
            thread.join(timeout=10)
            assert not thread.is_alive(), "异步服务应完成关闭"

    return running


@pytest.fixture
def rpc_channel(rpc_server_factory):
    with rpc_server_factory() as channel:
        yield channel


@pytest.fixture
def rpc(rpc_channel):
    return agent_pb2_grpc.AgentServiceStub(rpc_channel)
