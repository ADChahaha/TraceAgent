"""文档 QA 执行上下文：输入文档落盘后保存文件树、消息和配置，不保存对外事件或取消状态。"""

from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass

from service.file_extraction_agent.core.documents import DocumentFileTree
from service.file_extraction_agent.schemas import DocumentQaMessage, RunOptions


@dataclass
class GraphState:
    completion_id: str
    document: DocumentFileTree
    messages: list[DocumentQaMessage]
    run_options: RunOptions
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
