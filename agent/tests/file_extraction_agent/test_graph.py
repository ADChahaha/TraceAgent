from __future__ import annotations

import json

from langchain_core.messages import AIMessageChunk

from service.file_extraction_agent.manager import prepare_completion_state, run_completion_graph_stream
from service.file_extraction_agent.schemas import DocumentQaMessage, InputDocument


class FakeStreamingModel:
    def __init__(self):
        self.calls = [
            {
                "tool_name": "ls",
                "content": "我先看文档结构。",
                "arguments": {"path": ""},
            },
            {
                "tool_name": "grep",
                "content": "我搜索 termination 相关位置。",
                "arguments": {"query": "terminate", "max_results": 5},
            },
            {
                "tool_name": "read",
                "content": "我读取命中的终止条款。",
                "arguments": {"path": "/abs/0001-contract/0001-Termination/0001-termination.md"},
            },
            {
                "content": "答案：可以提前终止，但需要提前 30 天书面通知。[30 天书面通知](/abs/0001-contract/0001-Termination/0001-termination.md)",
            },
        ]

    def invoke(self, messages):
        del messages
        return self.calls.pop(0)


def _input(tmp_path):
    return prepare_completion_state(
        completion_id="cmp_123",
        documents=[
            InputDocument(
                filename="contract.html",
                html="""
                <h1 id="title">合同</h1>
                <h2 id="term">Termination</h2>
                <p id="p1">Either party may terminate this Agreement with 30 days written notice.</p>
                """,
            )
        ],
        messages=[DocumentQaMessage(role="user", content="Can this contract be terminated early?")],
        workspace_root=tmp_path,
    )


def _sse_payloads(events: list[str]) -> list[dict]:
    payloads = []
    for event in events:
        data_lines = [line.removeprefix("data: ") for line in event.splitlines() if line.startswith("data: ")]
        if data_lines:
            payloads.append(json.loads("\n".join(data_lines)))
    return payloads


def test_run_completion_graph_stream_yields_sse_events_and_terminal_completion(tmp_path):
    events = list(run_completion_graph_stream(_input(tmp_path), FakeStreamingModel()))

    assert all(event.endswith("\n\n") for event in events)
    payloads = _sse_payloads(events)
    assert payloads[0]["type"] == "completion.created"
    assert payloads[0]["id"] == "cmp_123"
    assert payloads[1]["type"] == "source_indexed"
    assert payloads[1]["result"]["workspace_root"] == str(tmp_path / "cmp_123")
    assert isinstance(payloads[1]["result"]["tree"], list)
    assert payloads[2]["type"] == "model_message"
    assert payloads[3]["type"] == "tool_started"
    assert payloads[3]["tool"] == "ls"
    assert payloads[-1]["type"] == "completion.completed"
    assert payloads[-1]["id"] == "cmp_123"
    assert [payload["seq"] for payload in payloads] == list(range(1, len(payloads) + 1))


def test_run_completion_graph_stream_flushes_after_each_tool_call(tmp_path):
    model = FakeStreamingModel()
    stream = iter(run_completion_graph_stream(_input(tmp_path), model))

    created = _sse_payloads([next(stream)])[0]
    source = _sse_payloads([next(stream)])[0]
    model_message = _sse_payloads([next(stream)])[0]
    tool_started = _sse_payloads([next(stream)])[0]

    assert created["type"] == "completion.created"
    assert source["type"] == "source_indexed"
    assert model_message["type"] == "model_message"
    assert tool_started["type"] == "tool_started"
    assert tool_started["tool"] == "ls"
    assert len(model.calls) == 3


def test_run_completion_graph_stream_honors_external_should_stop(tmp_path):
    class StopAfterFirstModel:
        def __init__(self):
            self.calls = 0

        def invoke(self, messages):
            del messages
            self.calls += 1
            if self.calls == 1:
                return {
                    "tool_name": "ls",
                    "content": "我先看结构。",
                    "arguments": {"path": ""},
                }
            return {"content": "最终答案。"}

    stop_after = {"value": False}
    state = _input(tmp_path)
    events = list(
        run_completion_graph_stream(
            state,
            StopAfterFirstModel(),
            should_stop=lambda: stop_after["value"],
        )
    )
    payloads = _sse_payloads(events)
    assert payloads[-1]["type"] == "completion.completed"
    assert state.events[-1]["type"] != "completion.cancelled"

    stop_after["value"] = True
    state2 = _input(tmp_path)
    events2 = list(
        run_completion_graph_stream(
            state2,
            StopAfterFirstModel(),
            should_stop=lambda: stop_after["value"],
        )
    )
    payloads2 = _sse_payloads(events2)
    assert payloads2[-1]["type"] == "completion.cancelled"


def test_should_stop_backfills_cancel_tool_replies_for_pending_tool_calls(tmp_path):
    class PendingToolModel:
        def __init__(self):
            self.calls = 0

        def bind_tools(self, tools, **kwargs):
            del tools, kwargs
            return self

        def stream(self, messages):
            del messages
            self.calls += 1
            yield AIMessageChunk(
                content="我先读文件。",
                tool_call_chunks=[
                    {"type": "tool_call_chunk", "name": "read", "args": '{"path":"/abs/0001-section/0001-block.md"}', "id": "call-read", "index": 0},
                ],
            )

    stop_after = {"value": True}
    state = _input(tmp_path)
    events = list(
        run_completion_graph_stream(
            state,
            PendingToolModel(),
            should_stop=lambda: stop_after["value"],
        )
    )
    payloads = _sse_payloads(events)
    cancel_replies = [p for p in payloads if p.get("type") == "tool_completed" and p.get("tool") == "read"]
    assert len(cancel_replies) >= 1
    result = cancel_replies[0].get("result", {})
    assert result.get("ok") is False
    assert "cancel" in str(result).lower()
    assert payloads[-1]["type"] == "completion.cancelled"


def test_should_stop_after_fulfilled_batch_does_not_duplicate_tool_replies(tmp_path):
    from service.file_extraction_agent.manager import _backfill_pending_tool_cancels

    state = _input(tmp_path)
    state.events.append(
        {
            "seq": state.next_seq,
            "type": "model_message",
            "content": "我先看结构。",
            "tool_calls": [{"id": "call-1", "name": "ls", "args": {"path": ""}}, {"id": "call-2", "name": "read", "args": {"path": "/x"}}],
            "is_final": False,
        }
    )
    state.next_seq += 1
    state.events.append(
        {
            "seq": state.next_seq,
            "type": "tool_completed",
            "tool": "ls",
            "args": {"path": ""},
            "result": {"ok": True, "text": "root"},
        }
    )
    state.next_seq += 1

    _backfill_pending_tool_cancels(state)

    tool_events = [e for e in state.events if e.get("type") == "tool_completed"]
    ls_count = sum(1 for e in tool_events if e.get("tool") == "ls")
    read_count = sum(1 for e in tool_events if e.get("tool") == "read")
    assert ls_count == 1
    assert read_count == 1
    read_event = next(e for e in tool_events if e.get("tool") == "read")
    assert read_event["result"]["ok"] is False
    assert "cancel" in str(read_event["result"]).lower()
