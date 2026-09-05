"""工具调用批次 → 按名称路由并行执行 → 共享 deadline 收集 → 按原顺序返回 ToolMessage。

未知工具、普通异常和超时转成失败结果；每项保留调用 ID、名称、参数与 artifact。
超时后不等待迟到线程，不改写已返回的结果，也不管理事件队列或 completion 状态。
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from langchain_core.messages import ToolMessage

from service.file_extraction_agent.core.messages import _plain_json


def _execute_tools_parallel(
    tool_calls: list[dict[str, Any]],
    tools: list[Any],
    timeout: float = 60.0,
) -> list[Any]:
    """并行调用工具 → 按共享期限收集结果 → 按原始 ID 返回 ToolMessage。

    普通异常与超时转失败消息；不等待迟到线程，不写共享事件或 action。
    """
    tool_map = {getattr(tool, "name", getattr(tool, "__name__", "")): tool for tool in tools}

    def run_one(call: dict[str, Any]) -> Any:
        selected = tool_map.get(call["name"])
        if selected is None:
            raise ValueError(f"unknown tool: {call['name']}")
        execute = getattr(selected, "invoke", None)
        if callable(execute):
            return execute(call.get("args") or {})
        return selected(**(call.get("args") or {}))

    pool = ThreadPoolExecutor(max_workers=max(1, len(tool_calls)))
    deadline = time.monotonic() + timeout
    futures = [(pool.submit(run_one, call), call) for call in tool_calls]
    ordered = []
    try:
        for future, call in futures:
            try:
                raw = future.result(timeout=max(0.0, deadline - time.monotonic()))
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
        pool.shutdown(wait=False, cancel_futures=True)
    return ordered
