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
                "arguments": {"path_id": "[0000]", "depth": 2, "reason": "查看输入文档。"},
            },
            {
                "tool_name": "read",
                "arguments": {
                    "path_id": "[0000.0001.0001.0001]",
                    "reason": "读取成立年份段落。",
                },
            },
            {
                "tool_name": "bind_evidence",
                "arguments": {
                    "field_id": "founded_year",
                    "reason": "当前段落写明公司成立年份，先绑定当前 read block。",
                },
            },
            {
                "tool_name": "review_evidences",
                "arguments": {
                    "field_id": "founded_year",
                    "reason": "展开成立年份候选 block 为 inline 证据。",
                },
            },
            {
                "tool_name": "write_field",
                "arguments": {
                    "field_id": "founded_year",
                    "value": 2020,
                    "final_evidence": [
                        {
                            "path_id": "[0000.0001.0001.0001]",
                            "sentences": ["S001"],
                        }
                    ],
                    "reason": "证据已绑定，提交成立年份。",
                },
            },
            {
                "tool_name": "submit_result",
                "arguments": {"reason": "提交最终结果。"},
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
    assert payloads[0]["type"] == "tool_started"
    assert payloads[0]["tool"] == "tree"
    assert payloads[-1]["type"] == "result_completed"
    assert payloads[-1]["result"]["fields"] == [
        {
            "field_id": "founded_year",
            "status": "resolved",
            "value": 2020,
            "evidence": [
                {
                    "path_id": "[0000.0001.0001.0001]",
                    "sentences": ["S001"],
                }
            ],
            "evidence_texts": [
                {
                    "path_id": "[0000.0001.0001.0001]",
                    "selector": "S001",
                    "text": "公司成立于2020年。",
                }
            ],
            "reason": "证据已绑定，提交成立年份。",
        }
    ]
    assert [payload["seq"] for payload in payloads] == list(range(1, len(payloads) + 1))


def test_run_extraction_graph_stream_flushes_events_after_each_tool_call():
    model = FakeSlowModel()
    stream = iter(run_extraction_graph_stream(_input(), model))

    first_event = json.loads(next(stream))

    assert first_event["type"] == "tool_started"
    assert first_event["tool"] == "tree"
    assert len(model.calls) == 5


def test_map_state_to_result_returns_new_field_result_shape():
    state = build_graph_state(_input())
    state.field_states["founded_year"] = {
        "field_id": "founded_year",
        "status": "resolved",
        "value": 2020,
        "evidence": [
            {
                "path_id": "[0000.0001.0001.0001]",
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
                "field_id": "founded_year",
                "status": "resolved",
                "value": 2020,
                "evidence": [
                    {
                        "path_id": "[0000.0001.0001.0001]",
                        "sentences": ["S001"],
                    }
                ],
                "evidence_texts": [
                    {
                        "path_id": "[0000.0001.0001.0001]",
                        "selector": "S001",
                        "text": "公司成立于2020年。",
                    }
                ],
                "reason": "S001 写明公司成立于2020年。",
            }
        ]
    }
    assert "soft_plan" not in result.trace
