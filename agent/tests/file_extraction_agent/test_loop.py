from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock
from tests.async_helpers import async_items, wait_event
import json
import random
from types import SimpleNamespace
import pytest
from service.document_resources.schemas import InputDocument
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from service.file_extraction_agent.core import loop as qa_module
from service.file_extraction_agent.core.model_invocation import _invoke_model_message
from service.file_extraction_agent.core import model_invocation
from service.file_extraction_agent.core.messages import build_qa_messages
from service.file_extraction_agent.core import executor
from service.file_extraction_agent.core.graph import build_qa_graph
from service.file_extraction_agent.core.tools import build_tools
from service.document_resources.documents import materialize_tree
from service.file_extraction_agent.core.tools.workspace import DocumentFileTree
from service.file_extraction_agent.schemas import RunOptions
from service.file_extraction_agent.schemas import DocumentQaMessage


async def test_qa_stream_yields_only_original_messages(tmp_path, monkeypatch, resource_path):
    from unittest.mock import Mock, AsyncMock
    from service.file_extraction_agent.core.model import ChatModelFallbackChain, ModelCallAttempt

    provider = Mock(spec=["bind_tools", "ainvoke"])
    provider.bind_tools.return_value = provider
    provider.ainvoke = AsyncMock()
    first = AIMessage(content="读取结构", tool_calls=[{"id": "ls-1", "name": "ls", "args": {}}])
    final = AIMessage(content="完成", response_metadata={"finish_reason": "stop"})
    provider.ainvoke.side_effect = [first, final]
    model = ChatModelFallbackChain([ModelCallAttempt("test", provider, False)])
    messages = [
        item
        async for item in qa_module.run_qa_stream(
            resource_path=resource_path, messages=_state(tmp_path).messages, qa_model=model
        )
    ]
    assert len(messages) == 3
    assert messages[0] is first
    assert isinstance(messages[1], list)
    assert messages[1][0].tool_call_id == "ls-1"
    assert messages[2] is final


def test_tool_context_has_no_event_or_runtime_buffers(tmp_path):
    state = _state(tmp_path)
    for field in (
        "completion_id",
        "task_id",
        "events",
        "actions",
        "next_seq",
        "events_lock",
        "tool_batch_active",
        "current_model_content",
        "failed_stage",
    ):
        assert not hasattr(state, field), field


async def test_qa_requires_tool_binding_before_invoking_model(tmp_path, resource_path):
    calls = []
    model = SimpleNamespace(invoke=lambda messages: calls.append(messages) or {"content": "旧协议答案"})
    with pytest.raises((TypeError, AttributeError), match="bind_tools"):
        [
            item
            async for item in qa_module.run_qa_stream(
                resource_path=resource_path, messages=_state(tmp_path).messages, qa_model=model
            )
        ]
    assert calls == []


async def test_tool_timeout_emits_one_matching_result_and_discards_late_success(tmp_path):
    import threading
    from service.file_extraction_agent.core.tools.base import run_tool

    state = _state(tmp_path)
    release = threading.Event()
    finished = threading.Event()

    class SlowTool:
        name = "read"

        def invoke(self, args):
            try:
                return run_tool(lambda: (release.wait(2), {"ok": True})[1])
            finally:
                finished.set()

    try:
        messages = await executor._execute_tools_parallel(
            [{"id": "slow", "name": "read", "args": {"path": "x"}}], [SlowTool()], timeout=0.02
        )
        result = json.loads(messages[0].content)
        assert messages[0].artifact == result
        assert messages[0].tool_call_id == "slow"
        assert messages[0].status == "error"
        assert "timeout" in result["errors"][0]["message"]
        snapshot = messages[0].model_dump()
    finally:
        release.set()
        assert finished.wait(2)
    assert messages[0].model_dump() == snapshot
    assert not hasattr(state, "events")


async def test_tool_exception_is_reported_consistently_without_timeout(tmp_path):
    state = _state(tmp_path)

    class BrokenTool:
        name = "read"

        def invoke(self, args):
            raise ValueError("invalid path")

    messages = await executor._execute_tools_parallel(
        [{"id": "broken", "name": "read", "args": {}}], [BrokenTool()], timeout=1
    )
    result = json.loads(messages[0].content)
    assert result["errors"][0]["message"] == "invalid path"
    assert messages[0].artifact == result
    assert messages[0].tool_call_id == "broken"
    assert messages[0].status == "error"


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


def _state(tmp_path):
    return _prepare_test_state(
        documents=[
            InputDocument(
                filename="company.html",
                html='\n                <h1 id="title">公司资料</h1>\n                <h2 id="summary">概况</h2>\n                <p id="p1">公司成立于2020年。</p>\n                ',
            )
        ],
        messages=[DocumentQaMessage(role="user", content="公司什么时候成立？")],
        workspace_root=tmp_path,
    )


def test_qa_messages_describe_qa_investigation_not_field_extraction(tmp_path):
    messages = build_qa_messages(_state(tmp_path).messages)
    system_content = messages[0].content
    human_content = messages[1].content
    assert len(messages) == 2
    assert "document" in system_content.lower()
    assert "answer" in system_content.lower()
    assert "evidence" in system_content.lower()
    assert "Use numeric citation labels in the final answer" in system_content
    assert "[1](documents/0001-contract/0001-section/0001-block.md)" in system_content
    assert "Do not use descriptive final citation labels" in system_content
    assert (
        "During investigation, use human-readable labels; in final answers, use numeric labels"
        in system_content
    )
    assert "Do not collect everything into one final Sources section" in system_content
    assert "put the numbered citation immediately after the sentence it supports" in system_content
    assert "task_spec" not in system_content
    assert "write_field" not in system_content
    assert "submit_result" not in system_content
    assert "公司什么时候成立？" in human_content
    assert "Context from prior turns" not in system_content
    assert "Investigate the documents" not in human_content


def test_qa_prompt_allows_direct_answers_without_forced_document_search(tmp_path):
    messages = build_qa_messages(_state(tmp_path).messages)
    system_content = messages[0].content
    assert "Answer directly when the question can be answered from conversation context" in system_content
    assert "general assistant identity/capability" in system_content
    assert "Use document tools when the user asks about document content" in system_content
    assert "ls / grep / read" in system_content
    assert "[ls, grep]" in system_content
    assert "[tree, grep, read]" not in system_content
    assert "When using document tools, show a brief investigation trace" in system_content
    assert "Do not inspect unrelated documents just to satisfy symmetry" in system_content
    assert "Show your thought process" not in system_content
    assert "One tool per turn" not in system_content


def test_qa_messages_preserve_openai_tool_history(tmp_path):
    state = _prepare_test_state(
        documents=[
            InputDocument(
                filename="company.html", html='<h1 id="title">公司资料</h1><p id="p1">公司成立于2020年。</p>'
            )
        ],
        messages=[
            DocumentQaMessage(role="user", content="查成立时间"),
            DocumentQaMessage(
                role="assistant",
                content="我先读公司概况。",
                tool_calls=[
                    {
                        "id": "call_read_company",
                        "type": "function",
                        "function": {
                            "name": "read",
                            "arguments": '{"path":"/abs/0001-contract/0001-section/0001-block.md"}',
                        },
                    }
                ],
            ),
            DocumentQaMessage(
                role="tool",
                tool_call_id="call_read_company",
                name="read",
                content='{"ok":true,"text":"公司成立于2020年。"}',
            ),
            DocumentQaMessage(role="user", content="所以是哪一年？"),
        ],
        workspace_root=tmp_path,
    )
    messages = build_qa_messages(state.messages)
    assert messages[1].type == "human"
    assert messages[2].type == "ai"
    assert messages[2].tool_calls[0]["id"] == "call_read_company"
    assert isinstance(messages[3], ToolMessage)
    assert messages[3].tool_call_id == "call_read_company"
    assert messages[4].type == "human"
    assert len(messages) == 5
    assert messages[-1].content == "所以是哪一年？"
    assert "Investigate the documents" not in messages[-1].content


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
                    {
                        "type": "tool_call_chunk",
                        "name": "ls",
                        "args": '{"path":""}',
                        "id": "call-1",
                        "index": 0,
                    },
                    {
                        "type": "tool_call_chunk",
                        "name": "read",
                        "args": json.dumps({"path": read_path}),
                        "id": "call-2",
                        "index": 1,
                    },
                ],
            )

    model = MultiToolModel()
    graph = build_qa_graph(
        model,
        build_tools(state),
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
                tool_call_chunks=[
                    {"type": "tool_call_chunk", "name": "ls", "args": "", "id": "call-1", "index": 1}
                ],
            )
            yield AIMessageChunk(
                content="", tool_call_chunks=[{"type": "tool_call_chunk", "args": '{"path":""', "index": 1}]
            )
            yield AIMessageChunk(
                content="", tool_call_chunks=[{"type": "tool_call_chunk", "args": "}", "index": 1}]
            )

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


async def test_qa_falls_back_from_stream_to_invoke_within_configured_transport():
    calls = []

    class FailingStreamModel:

        def __init__(self, name):
            self.name = name

        async def astream(self, messages):
            if False:
                yield None
            calls.append(f"{self.name}.stream")
            raise RuntimeError(f"{self.name} failed")

    class InvokeModel:

        def __init__(self, name):
            self.name = name

        async def ainvoke(self, messages):
            calls.append(f"{self.name}.invoke")
            return AIMessage(
                content="fallback invoke worked",
                tool_calls=[{"id": "call-1", "name": "ls", "args": {"path": ""}}],
            )

    class NeverCalledModel:

        async def ainvoke(self, messages):
            raise AssertionError("later fallback should not be called")

    class FallbackModel:

        def model_call_attempts(self):
            return [
                SimpleNamespace(
                    name="responses_stream", model=FailingStreamModel("responses"), use_stream=True
                ),
                SimpleNamespace(name="responses_invoke", model=InvokeModel("responses"), use_stream=False),
                SimpleNamespace(name="chat_completions_invoke", model=NeverCalledModel(), use_stream=False),
            ]

    message = await _invoke_model_message(FallbackModel(), ["messages"])
    assert calls == ["responses.stream", "responses.invoke"]
    assert message.content == "fallback invoke worked"
    assert message.tool_calls[0]["name"] == "ls"


async def test_qa_uses_ethernet_backoff_between_failed_provider_attempts(monkeypatch):
    calls = []
    sleeps = []

    class FailingStreamModel:

        def __init__(self, name):
            self.name = name

        async def astream(self, messages):
            if False:
                yield None
            calls.append(f"{self.name}.stream")
            raise TimeoutError(f"{self.name} timeout")

    class SuccessfulInvokeModel:

        async def ainvoke(self, messages):
            calls.append("invoke")
            return AIMessage(
                content="fallback invoke worked",
                tool_calls=[{"id": "call-1", "name": "ls", "args": {"path": ""}}],
            )

    class FallbackModel:

        def model_call_attempts(self):
            return [
                SimpleNamespace(
                    name="responses_stream", model=FailingStreamModel("responses"), use_stream=True
                ),
                SimpleNamespace(
                    name="chat_completions_stream", model=FailingStreamModel("chat"), use_stream=True
                ),
                SimpleNamespace(name="responses_invoke", model=SuccessfulInvokeModel(), use_stream=False),
            ]

    monkeypatch.setattr(
        model_invocation.asyncio, "sleep", AsyncMock(side_effect=lambda seconds: sleeps.append(seconds))
    )
    monkeypatch.setattr(random, "randint", lambda lower, upper: upper)
    monkeypatch.setattr(model_invocation, "PROVIDER_BACKOFF_SLOT_SECONDS", 0.01)
    message = await _invoke_model_message(FallbackModel(), ["messages"])
    assert calls == ["responses.stream", "chat.stream", "invoke"]
    assert sleeps == [0.01, 0.03]
    assert message.content == "fallback invoke worked"


async def test_qa_stops_after_provider_attempt_limit(monkeypatch):

    class FailingStreamModel:

        async def astream(self, messages):
            if False:
                yield None
            del messages
            raise TimeoutError("provider timeout")

    class FallbackModel:

        def model_call_attempts(self):
            return [
                SimpleNamespace(name=f"attempt_{index}", model=FailingStreamModel(), use_stream=True)
                for index in range(7)
            ]

    monkeypatch.setattr(model_invocation.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(random, "randint", lambda lower, upper: lower)
    with pytest.raises(RuntimeError) as exc:
        await _invoke_model_message(FallbackModel(), ["messages"])
    message = str(exc.value)
    assert "attempt_0" in message
    assert "attempt_4" in message
    assert "attempt_5" not in message


async def test_qa_retries_transport_when_provider_stop_signal_requires_missing_tool_calls():
    calls = []

    class IncompleteToolCallStreamModel:

        async def astream(self, messages):
            calls.append("responses.stream")
            assert messages == ["messages"]
            yield AIMessageChunk(
                content="我会先看文档结构，再决定下一步。", response_metadata={"finish_reason": "tool_calls"}
            )

    class CompleteToolCallInvokeModel:

        async def ainvoke(self, messages):
            calls.append("responses.invoke")
            assert messages == ["messages"]
            return AIMessage(
                content="我先看结构。",
                tool_calls=[{"id": "call-1", "name": "ls", "args": {"path": ""}}],
                response_metadata={"finish_reason": "tool_calls"},
            )

    class FallbackModel:

        def model_call_attempts(self):
            return [
                SimpleNamespace(
                    name="responses_stream", model=IncompleteToolCallStreamModel(), use_stream=True
                ),
                SimpleNamespace(
                    name="responses_invoke", model=CompleteToolCallInvokeModel(), use_stream=False
                ),
            ]

    message = await _invoke_model_message(FallbackModel(), ["messages"])
    assert calls == ["responses.stream", "responses.invoke"]
    assert message.content == "我先看结构。"
    assert message.tool_calls[0]["name"] == "ls"


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

    class FallbackModel:

        def model_call_attempts(self):
            return [SimpleNamespace(name="responses_stream", model=PlanOnlyModel(), use_stream=True)]

    try:
        await _invoke_model_message(FallbackModel(), ["messages"])
    except RuntimeError as exc:
        assert "terminal stop signal" in str(exc)
    else:
        raise AssertionError("plan-only message without terminal stop signal should fail")


async def test_parallel_tool_executor_runs_all_calls_concurrently(tmp_path):
    import threading
    from service.file_extraction_agent.core.executor import _execute_tools_parallel

    state = _state(tmp_path)
    gate = threading.Event()

    class GatedTool:
        name = "read"

        def invoke(self, args):
            del args
            gate.wait(timeout=1.0)
            return {"ok": True, "text": "done"}

    class FastTool:
        name = "ls"

        def invoke(self, args):
            del args
            gate.set()
            return {"ok": True, "text": "root"}

    calls = [
        {"id": "call-1", "name": "ls", "args": {"path": ""}},
        {"id": "call-2", "name": "read", "args": {"path": "/x"}},
    ]
    result = await _execute_tools_parallel(calls, tools=[FastTool(), GatedTool()], timeout=1.0)
    assert len(result) == 2
    assert {getattr(m, "tool_call_id", None) for m in result} == {"call-1", "call-2"}


async def test_parallel_tool_executor_times_out_slow_call(tmp_path):
    import time
    from service.file_extraction_agent.core.executor import _execute_tools_parallel

    state = _state(tmp_path)

    class SlowTool:
        name = "read"

        def invoke(self, args):
            del args
            time.sleep(2.0)
            return {"ok": True, "text": "late"}

    calls = [{"id": "call-1", "name": "read", "args": {"path": "/x"}}]
    result = await _execute_tools_parallel(calls, tools=[SlowTool()], timeout=0.05)
    assert len(result) == 1
    message = result[0]
    assert message.tool_call_id == "call-1"
    assert "timeout" in (getattr(message, "content", "") or "").lower()


def _prepare_test_state(*, documents, messages, workspace_root):
    """工具和 prompt 测试只准备文件树，不引入 completion 管理字段。"""
    return SimpleNamespace(
        document=DocumentFileTree.from_local_dir(materialize_tree(documents, workspace_root)),
        messages=messages,
        run_options=RunOptions(),
    )
