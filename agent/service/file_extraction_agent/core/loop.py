"""Agent 入口：workspace payload 与历史 → 绑定工具和消息 → 执行图 → 转换并输出类型化通知。

本模块消费 LangGraph messages/updates/custom，管理消息 ID 并转换增量、完整结果和失败通知。
节点路由由 graph 决定；无效输入抛 ValueError，执行异常向运行时传播，关闭时等待内层流清理。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Sequence
from contextlib import aclosing
from typing import Any, cast
from uuid import uuid4

from langchain_core.messages import AIMessage, AnyMessage, ToolMessage

from service.file_extraction_agent.core.contracts import (
    AgentOutput, MessageDelta, MessageStarted, ModelFailed, ModelRetry,
    QaModel, StopCheck, Tool,
)
from service.file_extraction_agent.core.graph import MODEL_MAX_ATTEMPTS, build_qa_graph
from service.file_extraction_agent.core.messages import build_qa_messages
from service.file_extraction_agent.core.tools import build_tools
from service.file_extraction_agent.schemas import DocumentQaMessage, RunOptions

QA_RECURSION_LIMIT = 10000


async def run_qa_stream(
    *,
    workspace: dict[str, Any],
    messages: list[DocumentQaMessage],
    qa_model: QaModel,
    run_options: RunOptions | None = None,
    should_stop: StopCheck | None = None,
) -> AsyncGenerator[AgentOutput, None]:
    """校验 messages/workspace → 绑定子进程工具 → 执行并消费图流 → 输出模型消息或单个工具结果。"""
    if not messages:
        raise ValueError("messages must be a non-empty list")
    if not workspace:
        raise ValueError("workspace is required")
    if should_stop is not None and should_stop():
        return
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


def _visible_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part if isinstance(part, str) else part.get("text", "")
            for part in content
            if isinstance(part, str) or isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


async def stream_qa_graph(
    *,
    qa_model: QaModel,
    tools: Sequence[Tool],
    messages: list[AnyMessage],
    run_options: RunOptions | None = None,
    should_stop: StopCheck | None = None,
) -> AsyncGenerator[AgentOutput, None]:
    """messages 通道输出可见增量 → updates 输出完整结果/重试 → 取消抑制迟到消息 → 关闭图流。"""
    graph = build_qa_graph(qa_model, tools, run_options, should_stop=should_stop)
    updates = graph.astream(
        {"messages": messages},
        stream_mode=["messages", "updates", "custom"],
        config={"recursion_limit": QA_RECURSION_LIMIT},
    )
    message_id = None
    emitted_text = False
    try:
        async for mode, output in updates:
            if mode == "custom":
                if isinstance(output, ToolMessage) and not (should_stop is not None and should_stop()):
                    yield output
                continue
            if mode == "messages":
                chunk, metadata = output
                if metadata.get("langgraph_node") != "agent":
                    continue
                if should_stop is not None and should_stop():
                    continue
                if message_id is None:
                    message_id = str(uuid4())
                    yield MessageStarted(message_id)
                text = _visible_text(chunk.content)
                if text:
                    emitted_text = True
                    yield MessageDelta(message_id, text)
                continue
            for node, update in output.items():
                if node == "agent":
                    if should_stop is not None and should_stop():
                        return
                    failure = update.get("model_failure")
                    batch = update.get("messages", [])
                    if not failure and not batch:
                        continue
                    if message_id is None:
                        message_id = str(uuid4())
                        yield MessageStarted(message_id)
                    if failure:
                        attempt = update["model_attempt"]
                        if attempt < MODEL_MAX_ATTEMPTS:
                            yield ModelRetry(
                                message_id, attempt + 1, MODEL_MAX_ATTEMPTS,
                                round(update["retry_delay_seconds"] * 1000), failure,
                            )
                        else:
                            yield ModelFailed(message_id, failure)
                    else:
                        message = cast(AIMessage, batch[0]).model_copy(update={"id": message_id})
                        # 自定义非 LangChain 模型不产生原生回调；只能在完成时交付正文。
                        text = _visible_text(message.content)
                        if text and not emitted_text:
                            yield MessageDelta(message_id, text)
                        yield message
                    message_id = None
                    emitted_text = False
    finally:
        await updates.aclose()


__all__ = ["run_qa_stream"]
