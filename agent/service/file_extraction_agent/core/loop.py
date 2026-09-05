"""路径、消息与配置 → 初始化依赖并建图 → 转发模型消息和工具批次 → 响应取消并关闭流。

本模块只驱动图更新。消息转换、模型调用和工具执行分别委托 messages.py、
model_invocation.py 与 executor.py；无效输入抛 ValueError，执行异常向运行时传播。
"""

from __future__ import annotations

from typing import Iterable

from langchain_core.messages import AIMessage, ToolMessage

from service.file_extraction_agent.core import messages as qa_messages, model_invocation
from service.file_extraction_agent.core.graph import build_qa_graph
from service.file_extraction_agent.core.model import ChatModelFallbackChain
from service.file_extraction_agent.core import executor
from service.file_extraction_agent.core.tools import build_tools
from service.file_extraction_agent.core.tools.workspace import open_workspace
from service.file_extraction_agent.schemas import DocumentQaMessage, RunOptions

QA_RECURSION_LIMIT = 10000


def run_qa_stream(
    *,
    resource_path: str,
    messages: list[DocumentQaMessage],
    qa_model: ChatModelFallbackChain | None,
    run_options: RunOptions | None = None,
    should_stop=None,
) -> Iterable[AIMessage | list[ToolMessage]]:
    """路径初始化工具、配置绑定执行器 → 仅消息进入图 → 完整工具批次后响应取消。"""
    if not messages:
        raise ValueError("messages must be a non-empty list")
    if not isinstance(resource_path, str) or not resource_path.strip():
        raise ValueError("resource_path is required")
    stopped = lambda: should_stop is not None and should_stop()
    if stopped():
        return
    tools = build_tools(open_workspace(resource_path))
    messages = qa_messages.build_qa_messages(messages)
    graph = build_qa_graph(
        qa_model, tools, run_options=run_options,
        invoke_model=model_invocation._invoke_model_message, execute_tools=executor._execute_tools_parallel,
    )
    updates = graph.stream(
        {"messages": messages},
        stream_mode="updates",
        config={"recursion_limit": QA_RECURSION_LIMIT},
    )
    try:
        for output in updates:
            for node, update in output.items():
                batch = update.get("messages", [])
                if node == "agent":
                    if stopped():
                        return
                    message = batch[0]
                    ids = [call["id"] for call in message.tool_calls]
                    if any(not call_id for call_id in ids) or len(set(ids)) != len(ids):
                        raise ValueError("tool calls require unique non-empty IDs")
                    yield message
                    if not message.tool_calls and stopped():
                        return
                else:
                    yield batch
                    if stopped():
                        return
    finally:
        updates.close()


__all__ = ["run_qa_stream"]
