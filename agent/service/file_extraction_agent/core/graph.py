"""固定模型与工具 → 构建模型 / 指数退避 / 工具节点 → 返回编译后的图。

本模块负责建图、节点执行、重试路由。工具结果通过 custom 逐项发布，取消传播至工具 Task；
模型失败经 updates 输出并路由至退避节点，取消异常保持传播。
"""

from __future__ import annotations

import asyncio
import json
import random
from collections.abc import Sequence
from typing import Literal

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.config import get_stream_writer
from langgraph.graph import StateGraph
from langgraph.graph.message import MessagesState
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from service.file_extraction_agent.core import executor, model_invocation
from service.file_extraction_agent.core.contracts import (
    ModelCallFailure,
    ModelInvoker,
    QaModel,
    Tool,
    ToolExecutor,
)
from service.file_extraction_agent.schemas import RunOptions

MODEL_MAX_ATTEMPTS = 5
RETRY_BASE_SECONDS = 0.5
RETRY_MAX_SECONDS = 8.0


class QaState(MessagesState):
    """完整历史及单次逻辑模型调用的重试状态；失败文本不进入历史。"""

    model_attempt: int
    model_failure: str | None
    retry_delay_seconds: float


async def _wait_retry(delay: float) -> None:
    await asyncio.sleep(delay)


def _retry_delay(attempt: int, failure: ModelCallFailure) -> float:
    """有效服务端等待优先；否则指数基数封顶后乘 0.75–1 的随机系数。"""
    if failure.retry_after_seconds is not None:
        return failure.retry_after_seconds
    base = min(RETRY_BASE_SECONDS * 2 ** min(attempt - 1, 1000), RETRY_MAX_SECONDS)
    return base * (1 - 0.25 * random.random())


def build_qa_graph(
    qa_model: QaModel,
    tools: Sequence[Tool],
    run_options: RunOptions | None = None,
    *,
    invoke_model: ModelInvoker | None = None,
    execute_tools: ToolExecutor | None = None,
) -> CompiledStateGraph[QaState, None, QaState, QaState]:
    """单次固定请求 → 失败转退避或结束，成功校验工具 ID → 工具批次 → 下一次请求。"""
    model = qa_model.bind_tools(tools)
    invoke = invoke_model or model_invocation._invoke_model_message
    execute = execute_tools or executor._execute_tools_parallel
    timeout = (run_options or RunOptions()).tool_execution_timeout

    async def call_model(state: QaState) -> Command[Literal["tools", "retry_wait", "__end__"]]:
        message = await invoke(model, state["messages"])
        attempt = state.get("model_attempt", 0) + 1
        if isinstance(message, ModelCallFailure):
            retry = attempt < MODEL_MAX_ATTEMPTS
            delay = _retry_delay(attempt, message) if retry else 0.0
            return Command(
                update={
                    "messages": [],
                    "model_attempt": attempt,
                    "model_failure": message.error,
                    "retry_delay_seconds": delay,
                },
                goto="retry_wait" if retry else "__end__",
            )
        ids = [call["id"] for call in message.tool_calls]
        if any(not call_id for call_id in ids) or len(set(ids)) != len(ids):
            raise ValueError("tool calls require unique non-empty IDs")
        return Command(
            update={
                "messages": [message], "model_attempt": 0,
                "model_failure": None, "retry_delay_seconds": 0.0,
            },
            goto="tools" if message.tool_calls else "__end__",
        )

    async def retry_wait(state: QaState) -> Command[Literal["agent", "__end__"]]:
        await _wait_retry(state["retry_delay_seconds"])
        return Command(update={"messages": []}, goto="agent")

    async def run_tools(state: MessagesState) -> Command[Literal["agent", "__end__"]]:
        message = state["messages"][-1]
        if not isinstance(message, AIMessage):
            raise TypeError("tools node requires an AIMessage")
        writer = get_stream_writer()
        published: dict[str, ToolMessage] = {}

        def emit(reply: ToolMessage) -> None:
            published[reply.tool_call_id] = reply
            writer(reply)

        try:
            replies = await execute(message.tool_calls, tools, timeout=timeout, on_result=emit)
        except Exception as exc:
            result = {"ok": False, "errors": [{"message": str(exc)}]}
            replies = [
                published[call["id"]] if call["id"] in published else ToolMessage(
                    content=json.dumps(result),
                    artifact=result,
                    status="error",
                    tool_call_id=call["id"],
                    name=call["name"],
                    additional_kwargs={"tool_args": call["args"]},
                )
                for call in message.tool_calls
            ]
        for reply in replies:
            if reply.tool_call_id not in published:
                emit(reply)
        return Command(update={"messages": replies}, goto="agent")

    graph = StateGraph(QaState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", run_tools)
    graph.add_node("retry_wait", retry_wait)
    graph.set_entry_point("agent")
    return graph.compile()
