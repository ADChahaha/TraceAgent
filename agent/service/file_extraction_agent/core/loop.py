"""Agent 入口：资源路径与历史 → 校验并初始化工具 → 构建模型消息 → 转发 graph 输出。

这里只组装流程，不解析 LangGraph 更新或决定节点路由；无效输入抛 ValueError，
执行异常向运行时传播，调用方关闭时同步关闭内层异步生成器。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import aclosing

from service.file_extraction_agent.core.contracts import AgentOutput, QaModel, StopCheck
from service.file_extraction_agent.core.graph import stream_qa_graph
from service.file_extraction_agent.core.messages import build_qa_messages
from service.file_extraction_agent.core.tools import build_tools
from service.file_extraction_agent.core.tools.workspace import open_workspace
from service.file_extraction_agent.schemas import DocumentQaMessage, RunOptions


async def run_qa_stream(
    *,
    resource_path: str,
    messages: list[DocumentQaMessage],
    qa_model: QaModel,
    run_options: RunOptions | None = None,
    should_stop: StopCheck | None = None,
) -> AsyncGenerator[AgentOutput, None]:
    """校验路径和消息 → 初始化共享工具上下文 → 委托 graph 执行 → 输出消息或工具批次。"""
    if not messages:
        raise ValueError("messages must be a non-empty list")
    if not isinstance(resource_path, str) or not resource_path.strip():
        raise ValueError("resource_path is required")
    if should_stop is not None and should_stop():
        return
    workspace = await asyncio.to_thread(open_workspace, resource_path)
    async with aclosing(
        stream_qa_graph(
            qa_model=qa_model,
            tools=build_tools(workspace),
            messages=build_qa_messages(messages),
            run_options=run_options,
            should_stop=should_stop,
        )
    ) as outputs:
        async for output in outputs:
            yield output


__all__ = ["run_qa_stream"]
