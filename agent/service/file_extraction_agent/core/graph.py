"""资源路径与消息 → 校验并加载资源 → 初始化问答执行状态，不携带管理 ID。"""

from dataclasses import dataclass

from service.document_resources import load_resource
from service.document_resources.documents import DocumentFileTree
from service.document_resources.search import EmbeddingIndex
from service.file_extraction_agent.schemas import DocumentQaMessage, RunOptions


@dataclass
class GraphState:
    document: DocumentFileTree
    messages: list[DocumentQaMessage]
    run_options: RunOptions
    index: EmbeddingIndex
    embedding_model: str
    embedding_backend: str


def build_graph_state(*, resource_path: str, messages: list[DocumentQaMessage], run_options: RunOptions | None = None) -> GraphState:
    if not messages:
        raise ValueError("messages must be a non-empty list")
    resource = load_resource(resource_path)
    return GraphState(
        document=resource.document, messages=messages, run_options=run_options or RunOptions(),
        index=resource.index, embedding_model=resource.embedding_model, embedding_backend=resource.embedding_backend,
    )
