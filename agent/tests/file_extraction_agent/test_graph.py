from __future__ import annotations

import json

from service.file_extraction_agent.impl.graph import run_completion_graph_stream
from service.file_extraction_agent.input_adapter import build_completion_input


class FakeStreamingModel:
    def __init__(self):
        self.calls = [
            {
                "tool_name": "tree",
                "content": "我先看文档结构。",
                "arguments": {"path_id": "", "depth": 2},
            },
            {
                "tool_name": "grep",
                "content": "我搜索 termination 相关位置。",
                "arguments": {"query": "terminate", "max_results": 5},
            },
            {
                "tool_name": "read",
                "content": "我读取命中的终止条款。",
                "arguments": {"locator": "evidence://0001.0001.0001.0001"},
            },
            {
                "tool_name": "inspect",
                "content": "这段说明任一方可提前 30 天书面通知终止。[终止条款](evidence://0001.0001.0001.0001)",
                "arguments": {"locator": "evidence://0001.0001.0001.0001"},
            },
            {
                "content": "答案：可以提前终止，但需要提前 30 天书面通知。[30 天书面通知](evidence://0001.0001.0001.0001/S001)",
            },
        ]

    def invoke(self, messages):
        del messages
        return self.calls.pop(0)


def _input():
    return build_completion_input(
        completion_id="cmp_123",
        documents=[
            {
                "filename": "contract.html",
                "html": """
                <h1 id="title">合同</h1>
                <h2 id="term">Termination</h2>
                <p id="p1">Either party may terminate this Agreement with 30 days written notice.</p>
                """,
            }
        ],
        messages=[{"role": "user", "content": "Can this contract be terminated early?"}],
    )


def _sse_payloads(events: list[str]) -> list[dict]:
    payloads = []
    for event in events:
        data_lines = [line.removeprefix("data: ") for line in event.splitlines() if line.startswith("data: ")]
        if data_lines:
            payloads.append(json.loads("\n".join(data_lines)))
    return payloads


def test_run_completion_graph_stream_yields_sse_events_and_terminal_completion():
    events = list(run_completion_graph_stream(_input(), FakeStreamingModel()))

    assert all(event.endswith("\n\n") for event in events)
    payloads = _sse_payloads(events)
    assert payloads[0]["type"] == "completion.created"
    assert payloads[0]["id"] == "cmp_123"
    assert payloads[1]["type"] == "source_indexed"
    assert payloads[1]["result"]["source_selectors"] == {
        "0001": "title",
        "0001.0001": "title",
        "0001.0001.0001": "term",
        "0001.0001.0001.0001": "p1",
    }
    assert payloads[2]["type"] == "model_message"
    assert payloads[3]["type"] == "tool_started"
    assert payloads[3]["tool"] == "tree"
    assert payloads[-1]["type"] == "completion.completed"
    assert payloads[-1]["id"] == "cmp_123"
    assert [payload["seq"] for payload in payloads] == list(range(1, len(payloads) + 1))


def test_run_completion_graph_stream_flushes_after_each_tool_call():
    model = FakeStreamingModel()
    stream = iter(run_completion_graph_stream(_input(), model))

    created = _sse_payloads([next(stream)])[0]
    source = _sse_payloads([next(stream)])[0]
    model_message = _sse_payloads([next(stream)])[0]
    tool_started = _sse_payloads([next(stream)])[0]

    assert created["type"] == "completion.created"
    assert source["type"] == "source_indexed"
    assert model_message["type"] == "model_message"
    assert tool_started["type"] == "tool_started"
    assert tool_started["tool"] == "tree"
    assert len(model.calls) == 4
