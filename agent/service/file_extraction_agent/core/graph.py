"""Reusable completion state for document-QA completions.

`GraphState` 是单 completion 的运行状态累积器（completion_id、文件树、消息、
运行选项、actions、events、next_seq）；`build_graph_state` 构造初始状态。
一轮 completion 的事件组装与 SSE 收口由 `manager.run_completion_graph_stream`
负责，不在此模块。
"""

from __future__ import annotations

import threading
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

from service.file_extraction_agent.core.documents import DocumentFileTree
from service.file_extraction_agent.schemas import DocumentQaMessage, RunOptions


@dataclass
class GraphState:
    completion_id: str
    document: DocumentFileTree
    messages: list[DocumentQaMessage]
    run_options: RunOptions
    actions: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    current_model_content: str = ""
    next_seq: int = 1
    failed_stage: str | None = None
    events_lock: threading.Lock = field(default_factory=threading.Lock)
    tool_batch_active: bool = False
    task_id: str | None = None
    workspace_parent: Path | None = None


def build_graph_state(
    *,
    completion_id: str,
    document: DocumentFileTree,
    messages: list[DocumentQaMessage],
    run_options: RunOptions,
) -> GraphState:
    return GraphState(
        completion_id=completion_id,
        document=document,
        messages=messages,
        run_options=run_options,
    )


__all__ = ["GraphState", "build_graph_state"]
