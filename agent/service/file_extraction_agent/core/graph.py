"""模型、工具与运行配置 → 绑定 agent/tools 节点 → 按工具调用路由 → 编译消息图。

图状态只使用 MessagesState。模型调用与工具执行函数由 loop 注入，避免双向依赖。
agent 有 tool_calls 时进入 tools，否则结束；工具结果回到 agent。执行器整体异常
转换为对应调用的失败 ToolMessage，模型调用异常向外传播给流式驱动层处理。
"""

from __future__ import annotations

import json
from typing import Any, Callable

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import MessagesState

from service.file_extraction_agent.core.model import ChatModelFallbackChain
from service.file_extraction_agent.schemas import RunOptions


def build_qa_graph(
    qa_model: ChatModelFallbackChain | None,
    tools: list[Any],
    run_options: RunOptions | None = None,
    *,
    invoke_model: Callable[[Any, list[Any]], AIMessage],
    execute_tools: Callable[..., list[ToolMessage]],
):
    """绑定模型、工具与超时配置 → 构建仅追加 messages 的 LangGraph。"""
    model = qa_model.bind_tools(tools)
    timeout = (run_options or RunOptions()).tool_execution_timeout

    def call_model(graph_state: MessagesState):
        message = invoke_model(model, graph_state["messages"])
        return {"messages": [message]}

    def run_tools(graph_state: MessagesState):
        last_message = graph_state["messages"][-1]
        tool_calls = getattr(last_message, "tool_calls", None)
        if not tool_calls:
            return {"messages": []}
        try:
            tool_messages = execute_tools(tool_calls, tools, timeout=timeout)
        except Exception as exc:
            result = {"ok": False, "errors": [{"message": str(exc)}]}
            tool_messages = [ToolMessage(
                content=json.dumps(result), artifact=result, status="error",
                tool_call_id=call["id"], name=call["name"], additional_kwargs={"tool_args": call["args"]},
            ) for call in tool_calls]
        return {"messages": tool_messages}

    def should_continue(graph_state: MessagesState):
        last_message = graph_state["messages"][-1]
        if getattr(last_message, "tool_calls", None):
            return "tools"
        return END

    def should_continue_after_tools(graph_state: MessagesState):
        del graph_state
        return "agent"

    graph = StateGraph(MessagesState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", run_tools)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    graph.add_conditional_edges("tools", should_continue_after_tools, {"agent": "agent", END: END})
    return graph.compile()
