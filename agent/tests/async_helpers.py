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
