"""异步测试辅助：事件序列替身与可超时的布尔等待。"""

import asyncio


async def async_items(items):
    for item in items:
        yield item


async def wait_event(event, timeout=None):
    try:
        await asyncio.wait_for(event.wait(), timeout)
        return True
    except TimeoutError:
        return False


async def wire_stream(workspace, qa_model, messages, run_options=None):
    """测试组合：service 执行事件 → 生产 protobuf 编码器，保留线级回归断言。"""
    from contextlib import aclosing
    from service.file_extraction_agent.application import stream_execution
    from routes.file_extraction_agent import encode_completion_stream
    async with aclosing(encode_completion_stream(stream_execution(workspace, qa_model, messages, run_options))) as events:
        async for event in events:
            yield event
