"""工具公共处理：execute() → 原样返回结果；普通异常 → ok:false 结果。

不读写事件或 action；manager 根据 ToolMessage 生成对外事件。
"""

from __future__ import annotations

from typing import Any, Callable


def order_key(name: str) -> int:
    """提取文件名数字前缀，用于工具浏览时保留文档顺序。"""
    digits = ""
    for char in name:
        if char.isdigit():
            digits += char
        else:
            break
    return int(digits) if digits else 0


def run_tool(
    state: Any,
    tool_name: str,
    args: dict[str, Any],
    execute: Callable[[], Any],
) -> Any:
    """执行工具并归一化异常；保留现有调用签名，不修改执行上下文。"""
    try:
        return execute()
    except Exception as exc:
        return {"ok": False, "errors": [{"message": str(exc)}]}


def expose_entries(entries: list[Any]) -> list[dict[str, Any]]:
    return [
        {"name": entry.name, "path": entry.path, "kind": entry.kind, "order": entry.order}
        for entry in entries
    ]


__all__ = ["run_tool", "expose_entries", "order_key"]
