# 异步测试辅助

`async_items` 将固定测试事件序列转换为异步迭代器；`wait_event` 等待 asyncio.Event，超时返回 False，供取消和并发断言使用。
