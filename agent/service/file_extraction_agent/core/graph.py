"""模型、工具和消息 → LangGraph 节点与路由 → AIMessage / 完整工具结果批次。

本模块负责建图、执行、更新转换、取消边界及图流关闭。已发布的工具调用必须完成
整批结果后停止；模型异常向外传播，执行器整体异常转换为对应批次的失败消息。
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Sequence
from typing import Literal, cast

from langchain_core.messages import AIMessage, AnyMessage, ToolMessage
from langgraph.graph import StateGraph
from langgraph.graph.message import MessagesState
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from service.file_extraction_agent.core import executor, model_invocation
from service.file_extraction_agent.core.contracts import (
    AgentOutput,
    ModelInvoker,
    QaModel,
    StopCheck,
    Tool,
    ToolExecutor,
)
from service.file_extraction_agent.schemas import RunOptions

QA_RECURSION_LIMIT = 10000


def build_qa_graph(
    qa_model: QaModel,
    tools: Sequence[Tool],
    run_options: RunOptions | None = None,
    *,
    should_stop: StopCheck | None = None,
    invoke_model: ModelInvoker | None = None,
    execute_tools: ToolExecutor | None = None,
) -> CompiledStateGraph[MessagesState, None, MessagesState, MessagesState]:
    """绑定依赖 → 模型节点校验调用 ID → 工具节点补齐结果 → 根据取消或回答结束路由。"""
    model = qa_model.bind_tools(tools)
    invoke = invoke_model or model_invocation._invoke_model_message
    execute = execute_tools or executor._execute_tools_parallel
    timeout = (run_options or RunOptions()).tool_execution_timeout

    def stopped() -> bool:
        return should_stop is not None and should_stop()

    async def call_model(state: MessagesState) -> Command[Literal["tools", "__end__"]]:
        if stopped():
            return Command(update={"messages": []}, goto="__end__")
        message = await invoke(model, state["messages"])
        if stopped():
            return Command(update={"messages": []}, goto="__end__")
        ids = [call["id"] for call in message.tool_calls]
        if any(not call_id for call_id in ids) or len(set(ids)) != len(ids):
            raise ValueError("tool calls require unique non-empty IDs")
        return Command(
            update={"messages": [message]}, goto="tools" if message.tool_calls else "__end__"
        )

    async def run_tools(state: MessagesState) -> Command[Literal["agent", "__end__"]]:
        message = state["messages"][-1]
        if not isinstance(message, AIMessage):
            raise TypeError("tools node requires an AIMessage")
        try:
            replies = await execute(message.tool_calls, tools, timeout=timeout)
        except Exception as exc:
            result = {"ok": False, "errors": [{"message": str(exc)}]}
            replies = [
                ToolMessage(
                    content=json.dumps(result),
                    artifact=result,
                    status="error",
                    tool_call_id=call["id"],
                    name=call["name"],
                    additional_kwargs={"tool_args": call["args"]},
                )
                for call in message.tool_calls
            ]
        return Command(update={"messages": replies}, goto="__end__" if stopped() else "agent")

    graph = StateGraph(MessagesState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", run_tools)
    graph.set_entry_point("agent")
    return graph.compile()


async def stream_qa_graph(
    *,
    qa_model: QaModel,
    tools: Sequence[Tool],
    messages: list[AnyMessage],
    run_options: RunOptions | None = None,
    should_stop: StopCheck | None = None,
) -> AsyncGenerator[AgentOutput, None]:
    """消息进入图 → 仅转发本轮节点输出 → 抑制取消后的模型消息 → finally 关闭图流。"""
    graph = build_qa_graph(qa_model, tools, run_options, should_stop=should_stop)
    updates = cast(
        AsyncGenerator[dict[str, MessagesState], None],
        graph.astream(
            {"messages": messages},
            stream_mode="updates",
            config={"recursion_limit": QA_RECURSION_LIMIT},
        ),
    )
    try:
        async for output in updates:
            for node, update in output.items():
                batch = update["messages"]
                if not batch:
                    continue
                if node == "agent":
                    if should_stop is not None and should_stop():
                        return
                    yield cast(AIMessage, batch[0])
                else:
                    yield cast(list[ToolMessage], batch)
    finally:
        await updates.aclose()
