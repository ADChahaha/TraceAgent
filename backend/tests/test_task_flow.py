from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from backend.core.config import BackendSettings
from backend.main import create_app
from backend.services.agent_process import build_field_agent_process
from backend.services.route_policy import build_route_policy_request


TASK_SPEC = {
    "task_name": "civilized_dormitory",
    "fields": [
        {
            "field_name": "room_numbers",
            "display_name": "文明寝室房间号",
            "type": "string",
            "required": True,
            "critical": True,
        }
    ],
}


class FakeAgentClient:
    def __init__(self, route: str = "accept"):
        self.route = route
        self.document_calls: list[dict[str, Any]] = []
        self.extraction_calls: list[dict[str, Any]] = []
        self.route_policy_calls: list[dict[str, Any]] = []

    def process_document(
        self,
        *,
        file_bytes: bytes,
        filename: str,
        content_type: str | None,
        file_type: str,
    ) -> dict[str, Any]:
        self.document_calls.append(
            {
                "file_bytes": file_bytes,
                "filename": filename,
                "content_type": content_type,
                "file_type": file_type,
            }
        )
        text = "2-201 被列为文明寝室补充材料" if filename == "supplement.pdf" else "1-101、1-102 被列为文明寝室"
        return {
            "file_type": file_type,
            "filename": filename,
            "html": f'<h1 id="dp-h1-1">测试文档</h1><p id="dp-p-1">{text}</p>',
            "display_html": f'<h1 id="dp-h1-1">测试文档</h1><p id="dp-p-1">{text}</p>',
            "markdown": text,
            "md_list": [text],
            "blocks": [
                {
                    "text": text,
                    "page_no": 2,
                    "kind": "text",
                    "meta_info": {"source": "fake-agent"},
                }
            ],
            "meta_info": {"processor": "fake"},
            "warnings": [],
        }

    def extract_fields(
        self,
        *,
        html: str,
        task_spec: dict[str, Any],
        run_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.extraction_calls.append(
            {
                "html": html,
                "task_spec": task_spec,
                "run_options": run_options,
            }
        )
        ref = {
            "document_id": "doc_test",
            "page": 2,
            "span": "p:p1",
            "block_id": "dp-p-1",
        }
        return {
            "status": "completed",
            "failure_reason": None,
            "result": {
                "fields": [
                    {
                        "field_name": "room_numbers",
                        "status": "resolved",
                        "value": "1-101,1-102",
                    }
                ]
            },
            "trace": {
                "document_tree": [
                    {
                        "id": "dp-h1-1",
                        "type": "TITLE",
                        "text": "测试文档",
                        "children": [],
                    }
                ],
                "fields": [
                    {
                        "field_name": "room_numbers",
                        "status": "resolved",
                        "evidence": {
                            "block_ids": ["dp-p-1"],
                            "texts": ["1-101、1-102 被列为文明寝室"],
                            "refs": [ref],
                            "status": "candidate_resolved",
                            "notes": ["field decision referenced candidate_ids: c1"],
                        },
                        "related_fields": [],
                        "actions": [
                            {
                                "action_type": "search_grep",
                                "message": "文明寝室 OR 房间号",
                                "refs": [ref],
                                "used_in_final_decision": False,
                                "metadata": {
                                    "stage": "broad",
                                    "refs": ["dp-p-1:p:p1"],
                                },
                            },
                            {
                                "action_type": "add_broad_candidate",
                                "message": "召回文明寝室房间号候选",
                                "refs": [ref],
                                "used_in_final_decision": True,
                                "metadata": {
                                    "stage": "broad",
                                    "candidate_ids": ["c1"],
                                    "refs": ["dp-p-1:p:p1"],
                                },
                            },
                            {
                                "action_type": "finish_broad",
                                "message": "候选足够，结束 broad",
                                "refs": [],
                                "used_in_final_decision": False,
                                "metadata": {
                                    "stage": "broad",
                                    "status": "enough_evidence",
                                    "candidate_ids": [],
                                    "refs": [],
                                },
                            },
                            {
                                "action_type": "final_decision",
                                "message": "候选证据支持字段值",
                                "refs": [ref],
                                "used_in_final_decision": True,
                                "metadata": {
                                    "stage": "resolution",
                                    "candidate_ids": ["c1"],
                                    "refs": ["dp-p-1:p:p1"],
                                },
                            }
                        ],
                        "reason": "候选证据支持字段值",
                        "failure_reason": None,
                    }
                ],
                "warnings": [],
                "metadata": {"source": "fake-agent"},
            },
        }

    def evaluate_route_policy(
        self,
        *,
        task_spec: dict[str, Any],
        field_outputs: list[dict[str, Any]],
        refs_with_text: list[dict[str, Any]],
        field_processes: list[dict[str, Any]],
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        self.route_policy_calls.append(
            {
                "task_spec": task_spec,
                "field_outputs": field_outputs,
                "refs_with_text": refs_with_text,
                "field_processes": field_processes,
                "metadata": metadata,
            }
        )
        return {
            "status": "completed",
            "failure_reason": None,
            "field_routes": [
                {
                    "field_name": "room_numbers",
                    "route": self.route,
                    "route_reason": "测试 route policy 输出",
                    "needs_review": self.route != "accept",
                }
            ],
        "warnings": [],
        "metadata": {"source": "fake-agent"},
    }


class FakeFailedExtractionAgentClient(FakeAgentClient):
    def extract_fields(
        self,
        *,
        html: str,
        task_spec: dict[str, Any],
        run_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.extraction_calls.append(
            {
                "html": html,
                "task_spec": task_spec,
                "run_options": run_options,
            }
        )
        return {
            "status": "failed",
            "failure_reason": "resolution 执行失败: lookup_blocks action exceeded limit",
            "result": {
                "fields": [
                    {
                        "field_name": "room_numbers",
                        "status": "failed",
                        "value": None,
                    }
                ]
            },
            "trace": {
                "fields": [
                    {
                        "field_name": "room_numbers",
                        "status": "failed",
                        "evidence": {
                            "block_ids": ["dp-p-1"],
                            "texts": ["1-101、1-102 被列为文明寝室"],
                            "refs": [],
                            "status": "partial",
                            "notes": ["resolution 失败，沿用 broad evidence"],
                        },
                        "related_fields": [],
                        "actions": [
                            {
                                "action_type": "model_call_error",
                                "message": "resolution 执行失败: lookup_blocks action exceeded limit",
                                "refs": [],
                                "used_in_final_decision": False,
                            }
                        ],
                        "reason": None,
                        "failure_reason": "resolution 执行失败: lookup_blocks action exceeded limit",
                    }
                ],
                "warnings": [],
                "metadata": {"source": "fake-agent"},
            },
        }


class FakeMissingRequiredFieldRouteClient(FakeAgentClient):
    def extract_fields(
        self,
        *,
        html: str,
        task_spec: dict[str, Any],
        run_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.extraction_calls.append(
            {
                "html": html,
                "task_spec": task_spec,
                "run_options": run_options,
            }
        )
        return {
            "status": "completed",
            "failure_reason": None,
            "result": {},
            "trace": {
                "document_tree": [],
                "field_states": {},
                "actions": [],
            },
        }

    def evaluate_route_policy(
        self,
        *,
        task_spec: dict[str, Any],
        field_outputs: list[dict[str, Any]],
        refs_with_text: list[dict[str, Any]],
        field_processes: list[dict[str, Any]],
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        self.route_policy_calls.append(
            {
                "task_spec": task_spec,
                "field_outputs": field_outputs,
                "refs_with_text": refs_with_text,
                "field_processes": field_processes,
                "metadata": metadata,
            }
        )
        return {
            "status": "completed",
            "failure_reason": None,
            "field_routes": [
                {
                    "field_name": "room_numbers",
                    "route": "review",
                    "route_reason": "字段 room_numbers 是 required 字段，但 file_extraction_agent 没有返回该字段，需要人工复核或补录。",
                    "needs_review": True,
                }
            ],
            "warnings": [],
            "metadata": {"source": "fake-agent"},
        }


def build_app(tmp_path: Path, route: str = "accept"):
    fake_agent = FakeAgentClient(route=route)
    app = create_app(
        settings=BackendSettings(database_path=tmp_path / "backend.sqlite3"),
        agent_client=fake_agent,
    )
    return app, fake_agent


def test_failed_task_summary_returns_error_message(tmp_path: Path):
    fake_agent = FakeFailedExtractionAgentClient()
    app = create_app(
        settings=BackendSettings(database_path=tmp_path / "backend.sqlite3"),
        agent_client=fake_agent,
    )

    with TestClient(app) as client:
        response = client.post(
            "/tasks",
            data={
                "task_type": "civilized_dormitory",
                "task_spec": json.dumps(TASK_SPEC, ensure_ascii=False),
            },
            files={"file": ("sample.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )

        assert response.status_code == 200
        created = response.json()
        assert created["status"] == "pending"
        assert created["stage"] == "uploaded"
        assert created["error_message"] is None

        summary_response = client.get(f"/tasks/{created['task_id']}")
        assert summary_response.status_code == 200
        summary = summary_response.json()
        assert summary["status"] == "failed"
        assert summary["stage"] == "done"
        assert summary["error_message"] == "resolution 执行失败: lookup_blocks action exceeded limit"


def test_route_policy_request_counts_broad_copy_candidates_in_broad_stage():
    trace = {
        "field_name": "room_numbers",
        "evidence_json": json.dumps({"refs": [], "texts": []}, ensure_ascii=False),
        "actions_json": json.dumps(
            [
                {
                    "action_type": "add_broad_candidate",
                    "metadata": {"stage": "broad"},
                },
                {
                    "action_type": "copy_field_candidates",
                    "metadata": {
                        "stage": "broad",
                        "source_field_name": "room_rows",
                        "copied_candidate_count": 2,
                    },
                },
                {
                    "action_type": "add_resolution_candidate",
                    "metadata": {"stage": "resolution"},
                },
                {
                    "action_type": "count_field_candidates",
                    "metadata": {
                        "stage": "resolution",
                        "counted_field_name": "room_rows",
                        "count": 2,
                    },
                },
                {
                    "action_type": "final_decision",
                    "metadata": {"stage": "resolution"},
                },
            ],
            ensure_ascii=False,
        ),
        "reason": "候选证据支持字段值",
        "failure_reason": None,
    }

    request = build_route_policy_request(
        task_spec=TASK_SPEC,
        extracted_fields=[
            {
                "field_name": "room_numbers",
                "agent_status": "resolved",
                "agent_value_json": json.dumps("1-101,1-102", ensure_ascii=False),
                "reason": "候选证据支持字段值",
                "failure_reason": None,
            }
        ],
        field_traces=[trace],
        metadata={},
    )

    field_process = request["field_processes"][0]
    assert field_process["broad_extraction"]["candidate_action_count"] == 2
    assert field_process["field_resolution"]["candidate_action_count"] == 1
    assert field_process["field_resolution"]["counted_fields"] == [
        {"field_name": "room_rows", "count": 2}
    ]


def test_route_policy_request_summarizes_tool_name_actions():
    trace = {
        "field_name": "academic_paper_titles",
        "evidence_json": json.dumps({"refs": [], "texts": []}, ensure_ascii=False),
        "actions_json": json.dumps(
            [
                {
                    "tool_name": "table_extraction",
                    "args": {
                        "table_id": "p002_b001",
                        "sql": "SELECT \"论文题目\" FROM data WHERE \"作品类型\" = '学术论文'",
                        "reason": "筛选作品类型为学术论文的行",
                    },
                },
                {
                    "tool_name": "set_field",
                    "args": {
                        "name": "academic_paper_titles",
                        "status": "resolved",
                        "reason": "写入学术论文题目",
                    },
                },
            ],
            ensure_ascii=False,
        ),
        "reason": "写入学术论文题目",
        "failure_reason": None,
    }

    request = build_route_policy_request(
        task_spec={
            "task_name": "extract_academic_paper_titles",
            "fields": [
                {
                    "field_name": "academic_paper_titles",
                    "display_name": "学术论文题目",
                    "type": "list[string]",
                    "required": True,
                }
            ],
        },
        extracted_fields=[
            {
                "field_name": "academic_paper_titles",
                "agent_status": "resolved",
                "agent_value_json": json.dumps(["论文 A"], ensure_ascii=False),
                "reason": "写入学术论文题目",
                "failure_reason": None,
            }
        ],
        field_traces=[trace],
        metadata={},
    )

    field_process = request["field_processes"][0]
    assert field_process["broad_extraction"]["search_queries"] == [
        "SELECT \"论文题目\" FROM data WHERE \"作品类型\" = '学术论文'"
    ]
    assert field_process["broad_extraction"]["candidate_action_count"] == 1
    assert field_process["field_resolution"]["final_decision_used"] is True
    assert field_process["field_resolution"]["reason"] == "写入学术论文题目"


def test_route_policy_request_preserves_table_and_query_audit_summaries():
    trace = {
        "field_name": "academic_paper_titles",
        "evidence_json": json.dumps({"refs": [], "texts": []}, ensure_ascii=False),
        "actions_json": json.dumps(
            [
                {
                    "tool_name": "table_extraction",
                    "args": {
                        "table_id": "p002_b001",
                        "sql": "SELECT \"论文题目\" FROM data WHERE \"作品类型\" = '学术论文'",
                        "reason": "筛选作品类型为学术论文的行",
                    },
                    "result": {
                        "table_id": "p002_b001",
                        "columns": ["论文题目"],
                        "row_count": 14,
                        "rows": [
                            {
                                "row_id": "p002_b001_tr_001",
                                "values": {"论文题目": "论文 A"},
                                "evidence_ids": ["p002_b001", "p002_b001_tr_001"],
                            }
                        ],
                        "table_audit": {
                            "row_count": 14,
                            "column_count": 3,
                            "blank_cells": {
                                "total_blank_cell_count": 1,
                                "by_column": [
                                    {
                                        "column": "作品类型",
                                        "blank_count": 1,
                                        "blank_row_ids_sample": ["p002_b001_tr_007"],
                                    }
                                ],
                                "cell_texts": ["不应该进入 route policy"],
                            },
                            "structure_signals": [],
                        },
                        "query_audit": {
                            "summary": "返回 14 行；筛选列“作品类型”空白 1 行；非空分布：学术论文 14；输出列“论文题目”无空值。",
                            "predicate_columns": [
                                {
                                    "column": "作品类型",
                                    "literal": "学术论文",
                                    "blank_count": 1,
                                    "blank_row_ids_sample": ["p002_b001_tr_007"],
                                    "row_values": {"作品类型": "", "论文题目": "不应该进入 route policy"},
                                }
                            ],
                        },
                    },
                },
                {
                    "tool_name": "set_field",
                    "args": {
                        "name": "academic_paper_titles",
                        "status": "resolved",
                        "reason": "写入学术论文题目",
                    },
                },
            ],
            ensure_ascii=False,
        ),
        "reason": "写入学术论文题目",
        "failure_reason": None,
    }

    request = build_route_policy_request(
        task_spec={
            "task_name": "extract_academic_paper_titles",
            "fields": [
                {
                    "field_name": "academic_paper_titles",
                    "display_name": "学术论文题目",
                    "type": "list[string]",
                    "required": True,
                }
            ],
        },
        extracted_fields=[
            {
                "field_name": "academic_paper_titles",
                "agent_status": "resolved",
                "agent_value_json": json.dumps(["论文 A"], ensure_ascii=False),
                "reason": "写入学术论文题目",
                "failure_reason": None,
            }
        ],
        field_traces=[trace],
        metadata={},
    )

    diagnostics = request["field_processes"][0]["broad_extraction"]["diagnostics"]
    assert diagnostics == [
        {
            "source": "table_extraction",
            "table_id": "p002_b001",
            "query": "SELECT \"论文题目\" FROM data WHERE \"作品类型\" = '学术论文'",
            "quality_type": "table_audit",
            "issues": [],
            "summary": "表格 14 行；3 列；空白单元格：作品类型 空白 1 行。",
        },
        {
            "source": "table_extraction",
            "table_id": "p002_b001",
            "query": "SELECT \"论文题目\" FROM data WHERE \"作品类型\" = '学术论文'",
            "quality_type": "query_audit",
            "issues": [],
            "summary": "返回 14 行；筛选列“作品类型”空白 1 行；非空分布：学术论文 14；输出列“论文题目”无空值。",
        },
    ]
    assert "status" not in diagnostics[0]
    assert "status" not in diagnostics[1]
    assert "row_values" not in json.dumps(diagnostics, ensure_ascii=False)
    assert "不应该进入 route policy" not in json.dumps(diagnostics, ensure_ascii=False)


def test_route_policy_request_preserves_query_audit_summary_without_raw_samples():
    trace = {
        "field_name": "civilized_dormitory_names",
        "evidence_json": json.dumps({"refs": [], "texts": []}, ensure_ascii=False),
        "actions_json": json.dumps(
            [
                {
                    "tool_name": "table_extraction",
                    "args": {
                        "table_id": "p001_b000",
                        "sql": "SELECT \"房间\" FROM data WHERE \"模范/文明\" = '文明寝室'",
                        "reason": "筛选类别为文明寝室的行",
                    },
                    "result": {
                        "table_id": "p001_b000",
                        "columns": ["房间"],
                        "row_count": 12,
                        "query_audit": {
                            "summary": "返回 12 行；筛选列“模范/文明”空白 149 行；非空分布：文明寝室 12，模范寝室 5；输出列“房间”无空值。",
                            "predicate_columns": [
                                {
                                    "column": "模范/文明",
                                    "literal": "文明寝室",
                                    "blank_count": 149,
                                    "blank_row_ids_sample": ["p001_b000_tr_001"],
                                    "non_empty_distribution": [
                                        {"value": "文明寝室", "count": 12},
                                        {"value": "模范寝室", "count": 5},
                                    ],
                                }
                            ],
                        },
                    },
                },
                {
                    "tool_name": "set_field",
                    "args": {
                        "name": "civilized_dormitory_names",
                        "status": "resolved",
                        "reason": "使用“模范/文明 = 文明寝室”筛出 12 行；空白行表示未获评普通寝室。",
                    },
                },
            ],
            ensure_ascii=False,
        ),
        "reason": "使用“模范/文明 = 文明寝室”筛出 12 行；空白行表示未获评普通寝室。",
        "failure_reason": None,
    }

    request = build_route_policy_request(
        task_spec={
            "task_name": "civilized_model_dormitory_names",
            "fields": [
                {
                    "field_name": "civilized_dormitory_names",
                    "display_name": "文明寝室名称",
                    "type": "list[string]",
                    "required": True,
                }
            ],
        },
        extracted_fields=[
            {
                "field_name": "civilized_dormitory_names",
                "agent_status": "resolved",
                "agent_value_json": json.dumps(["212", "214"], ensure_ascii=False),
                "reason": "使用“模范/文明 = 文明寝室”筛出 12 行；空白行表示未获评普通寝室。",
                "failure_reason": None,
            }
        ],
        field_traces=[trace],
        metadata={},
    )

    diagnostics = request["field_processes"][0]["broad_extraction"]["diagnostics"]
    assert diagnostics == [
        {
            "source": "table_extraction",
            "table_id": "p001_b000",
            "query": "SELECT \"房间\" FROM data WHERE \"模范/文明\" = '文明寝室'",
            "quality_type": "query_audit",
            "issues": [],
            "summary": "返回 12 行；筛选列“模范/文明”空白 149 行；非空分布：文明寝室 12，模范寝室 5；输出列“房间”无空值。",
        }
    ]
    assert "status" not in diagnostics[0]
    assert "blank_row_ids_sample" not in json.dumps(diagnostics, ensure_ascii=False)
    assert request["field_processes"][0]["field_resolution"]["reason"] == (
        "使用“模范/文明 = 文明寝室”筛出 12 行；空白行表示未获评普通寝室。"
    )


def test_route_policy_request_backfills_ref_text_from_document_blocks():
    trace = {
        "field_name": "room_numbers",
        "evidence_json": json.dumps(
            {
                "refs": [{"block_id": "dp-p-1"}],
                "texts": [],
                "status": "resolved",
            },
            ensure_ascii=False,
        ),
        "actions_json": json.dumps([], ensure_ascii=False),
        "reason": "候选证据支持字段值",
        "failure_reason": None,
    }

    request = build_route_policy_request(
        task_spec=TASK_SPEC,
        extracted_fields=[
            {
                "field_name": "room_numbers",
                "agent_status": "resolved",
                "agent_value_json": json.dumps("1-101,1-102", ensure_ascii=False),
                "reason": "候选证据支持字段值",
                "failure_reason": None,
            }
        ],
        field_traces=[trace],
        metadata={},
        block_lookup={
            "dp-p-1": {
                "document_id": "doc_1",
                "block_id": "dp-p-1",
                "text": "1-101、1-102 被列为文明寝室",
                "page_no": 2,
                "kind": "text",
            }
        },
    )

    ref = request["refs_with_text"][0]["refs"][0]
    assert ref["text"] == "1-101、1-102 被列为文明寝室"
    assert ref["document_id"] == "doc_1"
    assert ref["page"] == 2


def test_create_task_returns_pending_before_background_pipeline_finishes(tmp_path: Path):
    app, fake_agent = build_app(tmp_path, route="accept")

    with TestClient(app) as client:
        response = client.post(
            "/tasks",
            data={
                "task_type": "civilized_dormitory",
                "task_spec": json.dumps(TASK_SPEC, ensure_ascii=False),
            },
            files={"file": ("sample.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )

        assert response.status_code == 200
        created = response.json()
        assert created["status"] == "pending"
        assert created["stage"] == "uploaded"
        assert created["error_message"] is None

        assert fake_agent.document_calls
        summary_response = client.get(f"/tasks/{created['task_id']}")
        assert summary_response.status_code == 200
        assert summary_response.json()["status"] == "completed"


def test_create_task_accept_route_commits_agent_fields(tmp_path: Path):
    app, fake_agent = build_app(tmp_path, route="accept")

    with TestClient(app) as client:
        response = client.post(
            "/tasks",
            data={
                "task_type": "civilized_dormitory",
                "task_spec": json.dumps(TASK_SPEC, ensure_ascii=False),
            },
            files={"file": ("sample.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )

        assert response.status_code == 200
        created = response.json()
        assert created["status"] == "pending"
        assert created["stage"] == "uploaded"

        task_id = created["task_id"]
        task_response = client.get(f"/tasks/{task_id}")
        assert task_response.status_code == 200
        task_summary = task_response.json()
        assert task_summary["status"] == "completed"
        assert task_summary["stage"] == "done"
        assert task_summary["needs_review"] is False
        assert task_summary["route"] == "accept"

        result_response = client.get(f"/tasks/{task_id}/result")
        assert result_response.status_code == 200
        result_field = result_response.json()["fields"][0]
        assert result_field["field_name"] == "room_numbers"
        assert result_field["agent_value"] == "1-101,1-102"
        assert result_field["final_value"] == "1-101,1-102"
        assert result_field["source"] == "agent"
        assert result_field["committed"] is True

        audit_response = client.get(f"/tasks/{task_id}/audit")
        assert audit_response.status_code == 200
        commit = audit_response.json()["field_commits"][0]
        assert commit["field_name"] == "room_numbers"
        assert commit["route"] == "accept"
        assert commit["reviewed"] is False
        assert commit["used_global_lookup"] is False
        assert commit["used_validation_rule"] is False
        assert commit["action_types"] == [
            "search_grep",
            "add_broad_candidate",
            "finish_broad",
            "final_decision",
        ]
        assert commit["committed_by"] == "agent"
        assert commit["agent_process"]["actions"][0]["message"] == "文明寝室 OR 房间号"

        replay_response = client.get(f"/tasks/{task_id}/replay")
        assert replay_response.status_code == 200
        replay = replay_response.json()
        assert replay["outline_tree"] == [
            {
                "id": "dp-h1-1",
                "type": "TITLE",
                "text": "测试文档",
                "children": [],
            }
        ]

        extract_call = fake_agent.extraction_calls[0]
        assert extract_call["task_spec"] == TASK_SPEC
        assert "dp-p-1" in extract_call["html"]
        route_call = fake_agent.route_policy_calls[0]
        assert route_call["field_outputs"] == [
            {"field_name": "room_numbers", "status": "resolved", "value": "1-101,1-102"}
        ]
        assert route_call["refs_with_text"][0]["refs"][0]["text"] == "1-101、1-102 被列为文明寝室"
        assert route_call["field_processes"] == [
            {
                "field_name": "room_numbers",
                "broad_extraction": {
                    "status": "enough_evidence",
                    "search_queries": ["文明寝室 OR 房间号"],
                    "candidate_action_count": 1,
                    "counted_fields": [],
                    "finish_reason": "候选足够，结束 broad",
                },
                "field_resolution": {
                    "status": "resolved",
                    "search_queries": [],
                    "candidate_action_count": 0,
                    "counted_fields": [],
                    "final_decision_used": True,
                    "reason": "候选证据支持字段值",
                    "failure_reason": None,
                },
            }
        ]


def test_create_task_accepts_multiple_files_and_merges_document_blocks(tmp_path: Path):
    app, fake_agent = build_app(tmp_path, route="accept")

    with TestClient(app) as client:
        response = client.post(
            "/tasks",
            data={
                "task_type": "civilized_dormitory",
                "task_spec": json.dumps(TASK_SPEC, ensure_ascii=False),
            },
            files=[
                ("files", ("sample.pdf", b"%PDF-1.4 fake", "application/pdf")),
                (
                    "files",
                    (
                        "supplement.pdf",
                        b"%PDF-1.4 supplement",
                        "application/pdf",
                    ),
                ),
            ],
        )

        assert response.status_code == 200
        assert response.json()["status"] == "pending"
        assert response.json()["stage"] == "uploaded"
        assert [call["filename"] for call in fake_agent.document_calls] == [
            "sample.pdf",
            "supplement.pdf",
        ]

        extract_call = fake_agent.extraction_calls[0]
        assert "1-101、1-102 被列为文明寝室" in extract_call["html"]
        assert "2-201 被列为文明寝室补充材料" in extract_call["html"]

        trace_response = client.get(f"/tasks/{response.json()['task_id']}/trace")
        assert trace_response.status_code == 200
        steps = trace_response.json()["steps"]
        assert [step["agent"] for step in steps] == [
            "document_processor",
            "file_extraction_agent",
            "route_policy_agent",
        ]
        assert steps[0]["stage"] == "document_processing"
        assert steps[0]["status"] == "completed"
        assert steps[0]["summary"]["document_count"] == 2
        assert [document["filename"] for document in steps[0]["documents"]] == [
            "sample.pdf",
            "supplement.pdf",
        ]
        assert steps[0]["documents"][0]["block_count"] == 1
        assert steps[1]["stage"] == "extraction"
        assert steps[1]["status"] == "completed"
        assert steps[1]["summary"]["field_count"] == 1
        assert steps[1]["summary"]["warning_count"] == 0
        assert steps[1]["field_decisions"][0]["field_name"] == "room_numbers"
        assert steps[1]["field_decisions"][0]["value"] == "1-101,1-102"
        process_steps = steps[1]["field_decisions"][0]["process_steps"]
        assert [step["stage"] for step in process_steps] == [
            "broad_extraction",
            "field_resolution",
            "final_result",
            "route_validation",
        ]
        assert process_steps[0]["title"] == "第一步 broad extraction"
        assert process_steps[0]["evidence"]["status"] == "candidate_resolved"
        assert [action["action_type"] for action in process_steps[0]["actions"]] == [
            "search_grep",
            "add_broad_candidate",
            "finish_broad",
        ]
        assert process_steps[0]["evidence"]["texts"] == ["1-101、1-102 被列为文明寝室"]
        assert process_steps[0]["evidence"]["blocks"] == [
            {
                "block_id": "dp-p-1",
                "text": "1-101、1-102 被列为文明寝室",
                "kind": "text",
            }
        ]
        assert process_steps[1]["title"] == "第二步 resolution / tool"
        assert process_steps[1]["status"] == "used"
        assert process_steps[1]["output_fields"] == [
            {
                "field_name": "room_numbers",
                "status": "resolved",
                "value": "1-101,1-102",
                "reason": "候选证据支持字段值",
            }
        ]
        assert "执行 final_decision：候选证据支持字段值，参与最终定案。" in process_steps[1]["notes"]
        assert process_steps[1]["actions"][0]["action_type"] == "final_decision"
        assert process_steps[2]["title"] == "第三步 agent result（route 前）"
        assert process_steps[2]["value"] == "1-101,1-102"
        assert process_steps[2]["reason"] == "候选证据支持字段值"
        assert process_steps[3]["title"] == "第四步 route validation"
        assert process_steps[3]["status"] == "accept"
        assert process_steps[3]["route"] == "accept"
        assert process_steps[3]["needs_review"] is False
        assert process_steps[3]["reason"] == "测试 route policy 输出"
        assert steps[1]["field_decisions"][0]["actions"][1]["action_type"] == "add_broad_candidate"
        assert steps[1]["field_decisions"][0]["actions"][1]["message"] == "召回文明寝室房间号候选"
        assert steps[2]["stage"] == "route_policy"
        assert steps[2]["status"] == "completed"
        assert steps[2]["summary"]["routes"] == {
            "accept": 1,
            "review": 0,
            "reject": 0,
        }
        assert steps[2]["routes"] == [
            {
                "field_name": "room_numbers",
                "route": "accept",
                "needs_review": False,
                "route_reason": "测试 route policy 输出",
            }
        ]
        trace_field = trace_response.json()["fields"][0]
        assert trace_field["process_steps"][0]["stage"] == "broad_extraction"
        assert trace_field["process_steps"][1]["stage"] == "field_resolution"
        assert trace_field["process_steps"][2]["stage"] == "final_result"
        assert trace_field["process_steps"][3]["stage"] == "route_validation"

        agent_trace = trace_response.json()["agent_trace"]
        assert [event["agent"] for event in agent_trace] == [
            "document_processor",
            "document_processor",
            "file_extraction_agent",
            "route_policy_agent",
        ]
        assert [event["sequence"] for event in agent_trace] == [1, 2, 3, 4]
        assert agent_trace[0]["request"]["filename"] == "sample.pdf"
        assert agent_trace[0]["request"]["file_type"] == "pdf"
        assert agent_trace[0]["request"]["upload_size_bytes"] == len(b"%PDF-1.4 fake")
        assert "file_bytes" not in agent_trace[0]["request"]
        assert agent_trace[0]["response"]["markdown"] == "1-101、1-102 被列为文明寝室"
        assert agent_trace[1]["request"]["filename"] == "supplement.pdf"
        assert agent_trace[1]["response"]["blocks"][0]["text"] == "2-201 被列为文明寝室补充材料"
        assert agent_trace[2]["request"]["task_spec"] == TASK_SPEC
        assert agent_trace[2]["request"]["metadata"]["document_ids"]
        assert agent_trace[2]["response"]["result"]["fields"] == [
            {"field_name": "room_numbers", "status": "resolved", "value": "1-101,1-102"}
        ]
        assert "evidence" not in agent_trace[2]["response"]["result"]["fields"][0]
        assert agent_trace[2]["response"]["trace"]["fields"][0]["actions"][1]["action_type"] == "add_broad_candidate"
        assert agent_trace[2]["trace"]["fields"][0]["field_name"] == "room_numbers"
        assert agent_trace[3]["request"]["field_outputs"] == [
            {"field_name": "room_numbers", "status": "resolved", "value": "1-101,1-102"}
        ]
        assert agent_trace[3]["request"]["field_processes"][0]["broad_extraction"]["search_queries"] == [
            "文明寝室 OR 房间号"
        ]
        assert "refs" not in agent_trace[3]["request"]["field_processes"][0]["broad_extraction"]
        assert agent_trace[3]["response"]["field_routes"][0]["route"] == "accept"


def test_review_route_returns_handoff_and_accepts_revised_value(tmp_path: Path):
    app, fake_agent = build_app(tmp_path, route="review")

    with TestClient(app) as client:
        response = client.post(
            "/tasks",
            data={
                "task_type": "civilized_dormitory",
                "task_spec": json.dumps(TASK_SPEC, ensure_ascii=False),
            },
            files={
                "file": (
                    "sample.pdf",
                    b"%PDF-1.4 fake",
                    "application/pdf",
                )
            },
        )

        assert response.status_code == 200
        created = response.json()
        assert created["status"] == "pending"
        assert created["stage"] == "uploaded"
        task_id = created["task_id"]

        task_response = client.get(f"/tasks/{task_id}")
        assert task_response.status_code == 200
        task_summary = task_response.json()
        assert task_summary["status"] == "waiting_review"
        assert task_summary["stage"] == "review"

        review_response = client.get(f"/tasks/{task_id}/review")
        assert review_response.status_code == 200
        handoff = review_response.json()
        assert handoff["route"] == "review"
        assert handoff["fields"][0]["needs_review"] is True
        assert handoff["fields"][0]["evidence_texts"] == ["1-101、1-102 被列为文明寝室"]
        assert handoff["fields"][0]["actions"] == [
            "search_grep",
            "add_broad_candidate",
            "finish_broad",
            "final_decision",
        ]
        assert handoff["fields"][0]["agent_process"]["actions"][0]["message"] == "文明寝室 OR 房间号"
        assert handoff["fields"][0]["agent_process"]["process_steps"][0]["stage"] == "broad_extraction"
        assert handoff["fields"][0]["agent_process"]["process_steps"][1]["actions"][0]["action_type"] == "final_decision"
        assert handoff["fields"][0]["agent_process"]["process_steps"][2]["value"] == "1-101,1-102"
        assert handoff["fields"][0]["agent_process"]["process_steps"][3]["status"] == "review"
        assert handoff["fields"][0]["agent_process"]["process_steps"][3]["reason"] == "测试 route policy 输出"

        submit_response = client.post(
            f"/tasks/{task_id}/review",
            json={
                "decision": "revise_and_approve",
                "fields": [
                    {
                        "field_name": "room_numbers",
                        "review_value": "1-101,1-102,1-103",
                    }
                ],
                "comment": "人工补充遗漏房间",
                "reviewer": "teacher",
            },
        )
        assert submit_response.status_code == 200
        assert submit_response.json()["status"] == "completed"

        summary_response = client.get(f"/tasks/{task_id}")
        assert summary_response.status_code == 200
        summary = summary_response.json()
        assert summary["status"] == "completed"
        assert summary["stage"] == "done"
        assert summary["needs_review"] is False

        result_response = client.get(f"/tasks/{task_id}/result")
        result_field = result_response.json()["fields"][0]
        assert result_field["review_value"] == "1-101,1-102,1-103"
        assert result_field["final_value"] == "1-101,1-102,1-103"
        assert result_field["source"] == "human"
        assert result_field["committed"] is True

        audit_response = client.get(f"/tasks/{task_id}/audit")
        commit = audit_response.json()["field_commits"][0]
        assert commit["reviewed"] is True
        assert commit["review_decision"] == "revise_and_approve"
        assert commit["review_value"] == "1-101,1-102,1-103"
        assert commit["committed_by"] == "human"
        assert commit["agent_process"]["reason"] == "候选证据支持字段值"
        assert commit["action_types"] == [
            "search_grep",
            "add_broad_candidate",
            "finish_broad",
            "final_decision",
        ]
        assert commit["agent_process"]["actions"][1]["metadata"]["candidate_ids"] == ["c1"]
        assert commit["agent_process"]["process_steps"][0]["title"] == "第一步 broad extraction"
        assert commit["agent_process"]["process_steps"][1]["title"] == "第二步 resolution / tool"
        assert commit["agent_process"]["process_steps"][2]["title"] == "第三步 agent result（route 前）"
        assert commit["agent_process"]["process_steps"][3]["title"] == "第四步 route validation"
        assert fake_agent.document_calls[0]["file_type"] == "pdf"


def test_review_handoff_includes_missing_required_field_placeholder(tmp_path: Path):
    fake_agent = FakeMissingRequiredFieldRouteClient()
    app = create_app(
        settings=BackendSettings(database_path=tmp_path / "backend.sqlite3"),
        agent_client=fake_agent,
    )

    with TestClient(app) as client:
        response = client.post(
            "/tasks",
            data={
                "task_type": "civilized_dormitory",
                "task_spec": json.dumps(TASK_SPEC, ensure_ascii=False),
            },
            files={"file": ("sample.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )

        assert response.status_code == 200
        task_id = response.json()["task_id"]

        task_summary = client.get(f"/tasks/{task_id}").json()
        assert task_summary["status"] == "waiting_review"

        review_response = client.get(f"/tasks/{task_id}/review")
        assert review_response.status_code == 200
        handoff = review_response.json()
        assert len(handoff["fields"]) == 1
        field = handoff["fields"][0]
        assert field["field_name"] == "room_numbers"
        assert field["display_name"] == "文明寝室房间号"
        assert field["agent_value"] is None
        assert field["field_status"] == "failed"
        assert field["needs_review"] is True
        assert field["review_reason"] == "字段 room_numbers 是 required 字段，但 file_extraction_agent 没有返回该字段，需要人工复核或补录。"
        assert field["evidence_texts"] == []
        assert field["evidence_refs"] == []
        assert field["actions"] == []
        assert field["agent_process"]["status"] == "failed"

        submit_response = client.post(
            f"/tasks/{task_id}/review",
            json={
                "decision": "revise_and_approve",
                "fields": [
                    {
                        "field_name": "room_numbers",
                        "review_value": "1-101",
                    }
                ],
                "comment": "人工补录 required 字段",
                "reviewer": "teacher",
            },
        )
        assert submit_response.status_code == 200
        assert submit_response.json()["status"] == "completed"

        result_field = client.get(f"/tasks/{task_id}/result").json()["fields"][0]
        assert result_field["agent_value"] is None
        assert result_field["review_value"] == "1-101"
        assert result_field["final_value"] == "1-101"
        assert result_field["source"] == "human"


def test_agent_process_without_tool_actions_keeps_resolution_step_completed():
    process = build_field_agent_process(
        field_name="room_numbers",
        status="resolved",
        evidence={"block_ids": ["doc-1:p2:b3"], "texts": ["原始候选 block 正文"]},
        related_fields=[],
        actions=[],
        reason="字段由候选 block 直接定案",
        failure_reason=None,
        value="1-101",
        block_lookup={
            "doc-1:p2:b3": {
                "document_id": "doc-1",
                "block_id": "doc-1:p2:b3",
                "page": 2,
                "text": "原始候选 block 正文",
                "kind": "text",
            }
        },
    )

    process_steps = process["process_steps"]
    assert process_steps[0]["evidence"]["blocks"][0]["text"] == "原始候选 block 正文"
    assert process_steps[1]["stage"] == "field_resolution"
    assert process_steps[1]["status"] == "completed"
    assert process_steps[1]["output_fields"] == [
        {
            "field_name": "room_numbers",
            "status": "resolved",
            "value": "1-101",
            "reason": "字段由候选 block 直接定案",
        }
    ]
    assert process_steps[1]["notes"] == ["未记录额外 tool/action；resolution 直接将候选证据定案为字段输出。"]


def test_create_task_rejects_unsupported_file_type(tmp_path: Path):
    app, _fake_agent = build_app(tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/tasks",
            data={
                "task_type": "civilized_dormitory",
                "task_spec": json.dumps(TASK_SPEC, ensure_ascii=False),
            },
            files={"file": ("notes.txt", b"plain text", "text/plain")},
        )

        assert response.status_code == 422
        assert "unsupported file type" in response.json()["detail"]


def test_capabilities_returns_supported_task_and_routes(tmp_path: Path):
    app, _fake_agent = build_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/capabilities")

        assert response.status_code == 200
        payload = response.json()
        assert payload["supported_file_types"] == ["pdf"]
        assert payload["task_types"] == []
        assert payload["routes"] == ["accept", "review", "reject"]
        assert payload["review_decisions"] == ["approve", "revise_and_approve", "reject"]
        assert payload["features"] == {
            "trace": True,
            "review": True,
            "audit": True,
            "external_task_spec": True,
            "multiple_files": True,
        }


def test_create_task_requires_external_task_spec(tmp_path: Path):
    app, _fake_agent = build_app(tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/tasks",
            data={"task_type": "civilized_dormitory"},
            files={"file": ("sample.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )

        assert response.status_code == 422
        assert response.json()["detail"] == "task_spec is required"
