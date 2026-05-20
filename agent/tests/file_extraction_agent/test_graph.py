from __future__ import annotations

import json

from service.file_extraction_agent.impl.graph import map_state_to_result, run_extraction_graph_stream
from service.file_extraction_agent.impl.html_state import build_graph_state
from service.file_extraction_agent.input_adapter import build_graph_input


class FakeStreamingModel:
    def __init__(self):
        self.calls = [
            {
                "tool_name": "tree",
                "content": "查看输入文档。",
                "arguments": {"path_id": "evidence://0000", "depth": 2},
            },
            {
                "tool_name": "read",
                "content": "读取成立年份段落。",
                "arguments": {
                    "path_id": "evidence://0001.0001.0001",
                },
            },
            {
                "tool_name": "add_candidate_evidence",
                "content": "当前段落写明公司成立年份，先保存为候选证据。",
                "arguments": {
                    "field_id": "founded_year",
                    "path_id": "evidence://0001.0001.0001",
                },
            },
            {
                "tool_name": "review_evidences",
                "content": "展开成立年份候选 block 为 inline 证据。",
                "arguments": {
                    "field_id": "founded_year",
                },
            },
            {
                "tool_name": "write_field",
                "content": "候选证据复核后足够，提交成立年份。",
                "arguments": {
                    "field_id": "founded_year",
                    "value": 2020,
                    "final_evidence": [
                        "evidence://0001.0001.0001/S001"
                    ],
                },
            },
            {
                "tool_name": "submit_result",
                "content": "提交最终结果。",
                "arguments": {},
            },
        ]

    def invoke(self, messages):
        del messages
        return self.calls.pop(0)


class FakeSlowModel(FakeStreamingModel):
    pass


def _input():
    return build_graph_input(
        documents=[
            {
                "filename": "company.html",
                "html": """
                <h1 id="title">公司资料</h1>
                <h2 id="summary">概况</h2>
                <p id="p1">公司成立于2020年。</p>
                """,
            }
        ],
        task_spec={"fields": [{"name": "founded_year", "type": "number", "required": True}]},
    )


def test_run_extraction_graph_stream_yields_ndjson_events_and_final_result():
    events = list(run_extraction_graph_stream(_input(), FakeStreamingModel()))

    assert all(line.endswith("\n") for line in events)
    payloads = [json.loads(line) for line in events]
    assert payloads[0]["type"] == "source_indexed"
    assert payloads[0]["tool"] == "source_index"
    assert payloads[0]["result"]["source_selectors"] == {"0001.0001.0001": "p1"}
    assert payloads[1]["type"] == "tool_started"
    assert payloads[1]["tool"] == "tree"
    assert payloads[-1]["type"] == "result_completed"
    assert payloads[-1]["result"]["fields"] == [
        {
            "field_name": "founded_year",
            "status": "resolved",
            "value": 2020,
            "evidence": [
                {
                    "path_id": "0001.0001.0001",
                    "sentences": ["S001"],
                }
            ],
            "evidence_texts": [
                {
                    "path_id": "0001.0001.0001",
                    "selector": "S001",
                    "text": "公司成立于2020年。",
                }
            ],
            "reason": "候选证据复核后足够，提交成立年份。",
        }
    ]
    assert [payload["seq"] for payload in payloads] == list(range(1, len(payloads) + 1))


def test_run_extraction_graph_stream_flushes_events_after_each_tool_call():
    model = FakeSlowModel()
    stream = iter(run_extraction_graph_stream(_input(), model))

    first_event = json.loads(next(stream))
    second_event = json.loads(next(stream))

    assert first_event["type"] == "source_indexed"
    assert second_event["type"] == "tool_started"
    assert second_event["tool"] == "tree"
    assert len(model.calls) == 5


def test_map_state_to_result_returns_new_field_result_shape():
    state = build_graph_state(_input())
    state.field_states["founded_year"] = {
        "field_id": "founded_year",
        "status": "resolved",
        "value": 2020,
        "evidence": [
            {
                "path_id": "0001.0001.0001",
                "sentences": ["S001"],
            }
        ],
        "reason": "S001 写明公司成立于2020年。",
    }

    result = map_state_to_result(state)

    assert result.status == "completed"
    assert result.result == {
        "fields": [
            {
                "field_name": "founded_year",
                "status": "resolved",
                "value": 2020,
                "evidence": [
                    {
                        "path_id": "0001.0001.0001",
                        "sentences": ["S001"],
                    }
                ],
                "evidence_texts": [
                    {
                        "path_id": "0001.0001.0001",
                        "selector": "S001",
                        "text": "公司成立于2020年。",
                    }
                ],
                "reason": "S001 写明公司成立于2020年。",
            }
        ]
    }
    assert "soft_plan" not in result.trace
