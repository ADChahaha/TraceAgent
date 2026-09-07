"""工具调用批次 → create_task 并发 ainvoke → 共享 deadline 收集 → 按序返回 ToolMessage。

未知工具、普通异常和超时转成失败结果；每项保留调用 ID、名称、参数与 artifact。
超时或断连取消未完成协程；同步工具通过 to_thread 执行，迟到结果不改写已返回消息。
"""

from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any

from langchain_core.messages import ToolMessage

from service.file_extraction_agent.core.messages import _plain_json


async def _execute_tools_parallel(
    tool_calls: list[dict[str, Any]],
    tools: list[Any],
    timeout: float = 60.0,
) -> list[Any]:
    """并行调用工具 → 按共享期限收集结果 → 按原始 ID 返回 ToolMessage。

    普通异常与超时转失败消息；不等待迟到线程，不写共享事件或 action。
    """
    tool_map = {getattr(tool, "name", getattr(tool, "__name__", "")): tool for tool in tools}

    async def run_one(call: dict[str, Any]) -> Any:
        selected = tool_map.get(call["name"])
        if selected is None:
            raise ValueError(f"unknown tool: {call['name']}")
        execute = getattr(selected, "ainvoke", None)
        if callable(execute):
            return await execute(call.get("args") or {})
        if inspect.iscoroutinefunction(selected):
            return await selected(**(call.get("args") or {}))
        execute = getattr(selected, "invoke", None)
        if callable(execute):
            return await asyncio.to_thread(execute, call.get("args") or {})
        return await asyncio.to_thread(selected, **(call.get("args") or {}))

    tasks = [asyncio.create_task(run_one(call)) for call in tool_calls]
    ordered = []
    try:
        if not tasks:
            return []
        done, pending = await asyncio.wait(tasks, timeout=max(0.0, timeout))
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task, call in zip(tasks, tool_calls):
            try:
                if task not in done:
                    raise TimeoutError
                raw = task.result()
            except TimeoutError:
                raw = {"ok": False, "errors": [{"message": "tool execution timeout"}]}
            except Exception as exc:
                raw = {"ok": False, "errors": [{"message": str(exc)}]}
            result = _plain_json(raw)
            failed = isinstance(result, dict) and result.get("ok") is False
            ordered.append(ToolMessage(
                content=json.dumps(result, ensure_ascii=False) if isinstance(result, dict) else str(result or ""),
                artifact=result,
                status="error" if failed else "success",
                tool_call_id=call["id"], name=call["name"],
                additional_kwargs={"tool_args": call["args"]},
            ))
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return ordered
