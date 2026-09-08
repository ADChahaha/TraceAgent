"""工具调用批次 → create_task 并发 ainvoke → 共享 deadline 下逐项发布 → 按序返回历史 ToolMessage。

未知工具、普通异常和超时转成失败结果；每项保留调用 ID、名称、参数与 artifact。
超时或断连取消未完成协程；同步工具通过 to_thread 执行，迟到结果不改写已返回消息。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Sequence

from langchain_core.messages import ToolCall, ToolMessage

from service.file_extraction_agent.core.contracts import AsyncTool, Tool

from service.file_extraction_agent.core.messages import _plain_json


async def _execute_tools_parallel(
    tool_calls: list[ToolCall],
    tools: Sequence[Tool],
    timeout: float = 60.0,
    *, on_result: Callable[[ToolMessage], None] | None = None,
) -> list[ToolMessage]:
    """并行调用工具 → 完成一项立即回调 → 按原始 ID 返回完整历史。

    普通异常与超时转失败消息；不等待迟到线程，不写共享事件或 action。
    """
    tool_map = {tool.name: tool for tool in tools}

    async def invoke_one(call: ToolCall) -> object:
        selected = tool_map.get(call["name"])
        if selected is None:
            raise ValueError(f"unknown tool: {call['name']}")
        if isinstance(selected, AsyncTool):
            return await selected.ainvoke(call["args"])
        return await asyncio.to_thread(selected.invoke, call["args"])

    async def run_one(call: ToolCall) -> ToolMessage:
        try:
            raw = await invoke_one(call)
        except Exception as exc:
            raw = {"ok": False, "errors": [{"message": str(exc)}]}
        return make_message(call, raw)

    def make_message(call: ToolCall, raw: object) -> ToolMessage:
        result = _plain_json(raw)
        failed = isinstance(result, dict) and result.get("ok") is False
        return ToolMessage(
            content=json.dumps(result, ensure_ascii=False) if isinstance(result, dict) else str(result or ""),
            artifact=result, status="error" if failed else "success",
            tool_call_id=call["id"], name=call["name"],
            additional_kwargs={"tool_args": call["args"]},
        )

    tasks = [asyncio.create_task(run_one(call)) for call in tool_calls]
    positions = {task: index for index, task in enumerate(tasks)}
    results: dict[int, ToolMessage] = {}
    deadline = asyncio.get_running_loop().time() + max(0.0, timeout)
    pending = set(tasks)
    try:
        while pending:
            done, pending = await asyncio.wait(
                pending, timeout=max(0.0, deadline - asyncio.get_running_loop().time()),
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in sorted(done, key=positions.__getitem__):
                message = task.result()
                results[positions[task]] = message
                if on_result is not None:
                    on_result(message)
            if not done:
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                for task in sorted(pending, key=positions.__getitem__):
                    index = positions[task]
                    message = make_message(tool_calls[index], {
                        "ok": False, "errors": [{"message": "tool execution timeout"}],
                    })
                    results[index] = message
                    if on_result is not None:
                        on_result(message)
                break
    finally:
        for task in tasks:
            if not task.done() and not task.cancelling():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    # 实时结果已经逐项发布；完整返回值仅供图写入模型历史，保持调用顺序。
    return [results[index] for index in range(len(tasks))]
