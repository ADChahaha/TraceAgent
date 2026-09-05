"""Shared skeleton for model-facing QA tools over a real file tree.

`base.py` 提供所有工具共用的包装与事件记录基础，各具体工具（`ls` / `grep` /
`read` / `search_embedding`）都通过 `run_tool` 包装执行，保证每个工具调用都会
产出 `tool_started` / `tool_completed` / `tool_failed` 事件、写入 action 记录，
并把工具的分类与抛错统一收敛到这里。

实现步骤：

```text
run_tool(state, tool_name, args, execute)
  -> 先 emit tool_started（seq + type + tool + args）
  -> 执行 execute()，异常时统一转成 {ok: False, errors:[{message}]}
  -> 依据 result.ok 决定 tool_completed 或 tool_failed
  -> 记录 action 并 emit 对应事件
  -> 返回 result
```

`expose_entries` 等纯工具函数放在这里供各 tool 复用；`order_key` 为共享的文档树
命名排序函数，来自 `core/documents.py`，此处仅重新导出。

并行执行时由 `ToolExecution` 接管事件：构造时写开始 → `invoke` 设置本线程的
托管上下文，内层 `run_tool` 只执行 → 返回、异常或超时通过 `finish` 锁定唯一
结果并写 action/终态事件。托管上下文在 finally 复位，迟到结果不重复写入。
"""

from __future__ import annotations

from typing import Any, Callable
from contextvars import ContextVar
import threading

from service.file_extraction_agent.core.documents import order_key


_MANAGED_TOOL: ContextVar[bool] = ContextVar("managed_qa_tool", default=False)


class ToolExecution:
    """单次工具调用：开始事件 → 执行或超时竞争 → 固定唯一结果，丢弃迟到结果。"""

    def __init__(self, state: Any, name: str, args: dict[str, Any], call_id: str) -> None:
        self.state, self.name, self.args, self.call_id = state, name, args, call_id
        self._lock = threading.Lock()
        self._result: Any = None
        self._finished = False
        emit_event(state, {"type": "tool_started", "tool": name, "args": args, "tool_call_id": call_id})

    def invoke(self, execute: Callable[[], Any]) -> Any:
        token = _MANAGED_TOOL.set(True)
        try:
            try:
                result = execute()
            except Exception as exc:
                result = {"ok": False, "errors": [{"message": str(exc)}]}
            return self.finish(result)
        finally:
            _MANAGED_TOOL.reset(token)

    def finish(self, result: Any) -> Any:
        with self._lock:
            if not self._finished:
                self._finished = True
                self._result = result
                record_action(self.state, self.name, self.args, result)
                failed = isinstance(result, dict) and result.get("ok") is False
                emit_event(self.state, {
                    "type": "tool_failed" if failed else "tool_completed", "tool": self.name,
                    "args": self.args, "result": result, "tool_call_id": self.call_id,
                })
            return self._result


def run_tool(
    state: Any,
    tool_name: str,
    args: dict[str, Any],
    execute: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Wrap a tool execution, emitting started/completed/failed events."""

    if _MANAGED_TOOL.get():
        return execute()

    emit_event(
        state,
        {
            "type": "tool_started",
            "tool": tool_name,
            "args": args,
        },
    )
    try:
        result = execute()
    except Exception as exc:  # pragma: no cover - exercised by tool users
        result = {"ok": False, "errors": [{"message": str(exc)}]}
    event_type = "tool_completed" if result.get("ok") is not False else "tool_failed"
    record_action(state, tool_name, args, result)
    emit_event(
        state,
        {
            "type": event_type,
            "tool": tool_name,
            "args": args,
            "result": result,
        },
    )
    return result


def record_action(state: Any, tool_name: str, args: dict[str, Any], result: dict[str, Any]) -> None:
    action = {
        "tool_name": tool_name,
        "args": args,
        "result": result,
    }
    lock = getattr(state, "events_lock", None)
    if lock is not None:
        with lock:
            state.actions.append(action)
    else:
        state.actions.append(action)


def emit_event(state: Any, payload: dict[str, Any]) -> None:
    lock = getattr(state, "events_lock", None)
    if lock is not None:
        with lock:
            event = {"seq": state.next_seq, **payload}
            state.next_seq += 1
            state.events.append(event)
    else:
        event = {"seq": state.next_seq, **payload}
        state.next_seq += 1
        state.events.append(event)


def expose_entries(entries: list[Any]) -> list[dict[str, Any]]:
    return [
        {"name": entry.name, "path": entry.path, "kind": entry.kind, "order": entry.order}
        for entry in entries
    ]


__all__ = [
    "ToolExecution",
    "run_tool",
    "record_action",
    "emit_event",
    "expose_entries",
    "order_key",
]
