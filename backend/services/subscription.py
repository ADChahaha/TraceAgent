"""每个页面的有界增量队列；溢出或断连只关闭该订阅。"""

import asyncio
import copy
import json
import uuid


class SubscriptionClosed(Exception):
    pass


class Subscription:
    def __init__(self, *, max_events=256, max_bytes=4 * 1024 * 1024):
        self.id = uuid.uuid4().hex
        self.queue = asyncio.Queue(maxsize=max_events)
        self.max_bytes = max_bytes
        self.bytes = 0
        self.closed = asyncio.Event()
        self.ready = asyncio.Event()

    def publish(self, event):
        if self.closed.is_set():
            return False
        size = len(json.dumps(event, ensure_ascii=False).encode("utf-8"))
        if self.queue.full() or self.bytes + size > self.max_bytes:
            self.close()
            return False
        self.queue.put_nowait((copy.deepcopy(event), size))
        self.bytes += size
        self.ready.set()
        return True

    async def receive(self):
        while True:
            if self.closed.is_set():
                raise SubscriptionClosed()
            if not self.queue.empty():
                event, size = self.queue.get_nowait()
                self.bytes -= size
                return event
            self.ready.clear()
            # 仅等待通知；取消等待不会让另一个取队列任务偷走事件。
            await self.ready.wait()

    def close(self):
        self.closed.set()
        self.ready.set()
        while not self.queue.empty():
            self.queue.get_nowait()
        self.bytes = 0
