"""模型调用流合并、终止信号校验与图内并发工具调用测试。"""

from __future__ import annotations

import json
from types import SimpleNamespace

from document_service.document_resources.documents import materialize_tree
from document_service.document_resources.schemas import InputDocument
from langchain_core.messages import AIMessage, AIMessageChunk
from service.file_extraction_agent.core import executor, model_invocation
from service.file_extraction_agent.core.contracts import BoundModel, ModelCallFailure
from service.file_extraction_agent.core.graph import build_qa_graph
from service.file_extraction_agent.core.messages import build_qa_messages
from service.file_extraction_agent.core.model_invocation import _invoke_model_message
from service.file_extraction_agent.core.tools.workspace import DocumentFileTree
from service.file_extraction_agent.schemas import DocumentQaMessage, RunOptions


def _state(tmp_path):
    return SimpleNamespace(
        document=DocumentFileTree.from_local_dir(
            materialize_tree(
                [
                    InputDocument(
                        filename="company.html",
                        html='<h1 id="title">公司资料</h1><h2 id="summary">概况</h2><p id="p1">公司成立于2020年。</p>',
                    )
                ],
                tmp_path,
            )
        ),
        messages=[DocumentQaMessage(role="user", content="公司什么时候成立？")],
        run_options=RunOptions(),
    )


def _company_paragraph_path(state):
    def first_md(dir_path):
        for entry in state.document.entries(dir_path):
            if entry.kind == "dir":
                found = first_md(entry.path)
                if found:
                    return found
            elif entry.kind == "md":
                return entry.path
        return None

    for top in state.document.entries():
        if top.kind == "dir":
            found = first_md(top.path)
            if found:
                return found
    raise AssertionError("missing company paragraph")


def _async_tools(*names):
    class _Tool:
        def __init__(self, name):
            self.name = name

        async def ainvoke(self, args):
            return {"ok": True, "entries": [], "text": ""}

    return [_Tool(name) for name in names]


async def test_qa_graph_preserves_parallel_tool_calls(tmp_path):
    state = _state(tmp_path)
    read_path = _company_paragraph_path(state)

    class MultiToolModel:
        def __init__(self):
            self.calls = 0
            self.bind_kwargs = None

        def bind_tools(self, tools, **kwargs):
            del tools
            self.bind_kwargs = kwargs
            return self

        async def astream(self, messages):
            del messages
            self.calls += 1
            if self.calls > 1:
                yield AIMessageChunk(content="我已经看过结构。", response_metadata={"finish_reason": "stop"})
                return
            yield AIMessageChunk(
                content="我先看结构。",
                tool_call_chunks=[
                    {"type": "tool_call_chunk", "name": "ls", "args": '{"path":""}', "id": "call-1", "index": 0},
                    {"type": "tool_call_chunk", "name": "read", "args": json.dumps({"path": read_path}), "id": "call-2", "index": 1},
                ],
            )

    model = MultiToolModel()
    graph = build_qa_graph(
        model,
        _async_tools("ls", "read"),
        run_options=state.run_options,
        invoke_model=model_invocation._invoke_model_message,
        execute_tools=executor._execute_tools_parallel,
    )
    outputs = [
        item
        async for item in graph.astream(
            {"messages": build_qa_messages(state.messages)}, config={"recursion_limit": 4}
        )
    ]
    model_events = [update["agent"]["messages"][0] for update in outputs if "agent" in update]
    assert model.bind_kwargs == {}
    assert not hasattr(state, "actions")
    assert len(model_events[0].tool_calls) == 2
    assert [call["name"] for call in model_events[0].tool_calls] == ["ls", "read"]
    replies = next((update["tools"]["messages"] for update in outputs if "tools" in update))
    assert [reply.tool_call_id for reply in replies] == ["call-1", "call-2"]


async def test_qa_uses_responses_api_stream_and_merges_content_with_tool_calls():
    class StreamingModel:
        def __init__(self):
            self.streamed = False
            self.invoked = False

        async def astream(self, messages):
            self.streamed = True
            assert messages == ["messages"]
            yield AIMessageChunk(content=[{"type": "text", "text": "I will ", "index": 0}])
            yield AIMessageChunk(content=[{"type": "text", "text": "inspect root.", "index": 0}])
            yield AIMessageChunk(
                content="",
                tool_call_chunks=[{"type": "tool_call_chunk", "name": "ls", "args": "", "id": "call-1", "index": 1}],
            )
            yield AIMessageChunk(content="", tool_call_chunks=[{"type": "tool_call_chunk", "args": '{"path":""', "index": 1}])
            yield AIMessageChunk(content="", tool_call_chunks=[{"type": "tool_call_chunk", "args": "}", "index": 1}])

        async def ainvoke(self, messages):
            self.invoked = True
            raise AssertionError("stream should be used before invoke fallback")

    model = StreamingModel()
    message = await _invoke_model_message(model, ["messages"])
    assert model.streamed is True
    assert model.invoked is False
    assert isinstance(message, AIMessage)
    assert message.content == [{"type": "text", "text": "I will inspect root.", "index": 0}]
    assert message.tool_calls == [{"name": "ls", "args": {"path": ""}, "id": "call-1", "type": "tool_call"}]


async def test_qa_uses_explicit_non_streaming_model():
    class Provider:
        async def ainvoke(self, messages):
            return AIMessage(content="回答", response_metadata={"finish_reason": "stop"})

    result = await _invoke_model_message(BoundModel(Provider(), use_stream=False), [])
    assert result.content == "回答"


async def test_qa_returns_incomplete_response_failure():
    class IncompleteModel:
        async def astream(self, messages):
            yield AIMessageChunk(content="缺少工具", response_metadata={"finish_reason": "tool_calls"})

    result = await _invoke_model_message(IncompleteModel(), [])
    assert isinstance(result, ModelCallFailure)
    assert "without tool calls" in result.error


async def test_qa_accepts_terminal_stop_message_without_tool_calls():
    class FinalAnswerModel:
        async def astream(self, messages):
            del messages
            yield AIMessageChunk(content="最终答案。", response_metadata={"finish_reason": "stop"})

    message = await _invoke_model_message(FinalAnswerModel(), ["messages"])
    assert message.content == "最终答案。"
    assert message.tool_calls == []


async def test_qa_rejects_plan_only_message_without_terminal_stop_signal():
    class PlanOnlyModel:
        async def astream(self, messages):
            del messages
            yield AIMessageChunk(content="我会先在同一份入试要项里查相关依据。")

    result = await _invoke_model_message(PlanOnlyModel(), ["messages"])
    assert isinstance(result, ModelCallFailure)
    assert "terminal stop signal" in result.error
