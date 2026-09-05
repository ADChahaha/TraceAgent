"""资源路径与消息 → 校验执行输入 → GraphState；磁盘读取和 embedding 状态归工具层。"""

from dataclasses import dataclass

from service.file_extraction_agent.schemas import DocumentQaMessage, RunOptions


@dataclass
class GraphState:
    resource_path: str
    messages: list[DocumentQaMessage]
    run_options: RunOptions


def build_graph_state(*, resource_path: str, messages: list[DocumentQaMessage], run_options: RunOptions | None = None) -> GraphState:
    if not messages:
        raise ValueError("messages must be a non-empty list")
    if not isinstance(resource_path, str) or not resource_path.strip():
        raise ValueError("resource_path is required")
    return GraphState(resource_path, messages, run_options or RunOptions())
