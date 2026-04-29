from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from backend.core.config import BackendSettings
from backend.main import create_app
from backend.services.agent_process import build_field_agent_process


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
        text = "2-201 被列为文明寝室补充材料" if filename == "supplement.docx" else "1-101、1-102 被列为文明寝室"
        return {
            "file_type": file_type,
            "filename": filename,
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
        blocks: list[dict[str, Any]],
        markdown: str,
        md_list: list[str],
        task_spec: dict[str, Any],
        metadata: dict[str, Any],
        run_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.extraction_calls.append(
            {
                "blocks": blocks,
                "markdown": markdown,
                "md_list": md_list,
                "task_spec": task_spec,
                "metadata": metadata,
                "run_options": run_options,
            }
        )
        ref = {
            "document_id": blocks[0]["document_id"],
            "page": blocks[0]["page_no"],
            "block_id": blocks[0]["block_id"],
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
                "fields": [
                    {
                        "field_name": "room_numbers",
                        "status": "resolved",
                        "evidence": {
                            "block_ids": [blocks[0]["block_id"]],
                            "texts": ["1-101、1-102 被列为文明寝室"],
                            "refs": [ref],
                            "status": "model_resolved",
                            "notes": ["测试证据"],
                        },
                        "related_fields": ["building"],
                        "actions": [
                            {
                                "action_type": "field_reference",
                                "message": "模型请求参考字段 building",
                                "refs": [ref],
                                "used_in_final_decision": False,
                                "metadata": {
                                    "requested_field_name": "building",
                                    "returned_to_model": True,
                                },
                            },
                            {
                                "action_type": "global_lookup",
                                "message": "补查文明寝室名单",
                                "refs": [ref],
                                "used_in_final_decision": True,
                                "metadata": {
                                    "lookup_hints": ["文明寝室"],
                                    "returned_block_ids": [blocks[0]["block_id"]],
                                },
                            },
                            {
                                "action_type": "validation_rule",
                                "message": "校正房间号列表",
                                "refs": [ref],
                                "used_in_final_decision": True,
                            }
                        ],
                        "reason": "模型定案后经过规则校正",
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
        metadata: dict[str, Any],
        policy_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.route_policy_calls.append(
            {
                "task_spec": task_spec,
                "field_outputs": field_outputs,
                "refs_with_text": refs_with_text,
                "metadata": metadata,
                "policy_options": policy_options,
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
        blocks: list[dict[str, Any]],
        markdown: str,
        md_list: list[str],
        task_spec: dict[str, Any],
        metadata: dict[str, Any],
        run_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.extraction_calls.append(
            {
                "blocks": blocks,
                "markdown": markdown,
                "md_list": md_list,
                "task_spec": task_spec,
                "metadata": metadata,
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
                            "block_ids": [blocks[0]["block_id"]],
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
        assert commit["used_global_lookup"] is True
        assert commit["used_validation_rule"] is True
        assert commit["committed_by"] == "agent"
        assert commit["agent_process"]["actions"][0]["message"] == "模型请求参考字段 building"

        extract_call = fake_agent.extraction_calls[0]
        assert extract_call["task_spec"] == TASK_SPEC
        assert extract_call["blocks"][0]["document_id"].startswith("doc_")
        assert extract_call["blocks"][0]["block_id"].startswith("doc_")
        route_call = fake_agent.route_policy_calls[0]
        assert route_call["field_outputs"] == [
            {"field_name": "room_numbers", "status": "resolved", "value": "1-101,1-102"}
        ]
        assert route_call["refs_with_text"][0]["refs"][0]["text"] == "1-101、1-102 被列为文明寝室"


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
                        "supplement.docx",
                        b"fake docx",
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                ),
            ],
        )

        assert response.status_code == 200
        assert response.json()["status"] == "pending"
        assert response.json()["stage"] == "uploaded"
        assert [call["filename"] for call in fake_agent.document_calls] == [
            "sample.pdf",
            "supplement.docx",
        ]

        extract_call = fake_agent.extraction_calls[0]
        assert extract_call["markdown"] == (
            "1-101、1-102 被列为文明寝室\n\n"
            "2-201 被列为文明寝室补充材料"
        )
        assert extract_call["md_list"] == [
            "1-101、1-102 被列为文明寝室",
            "2-201 被列为文明寝室补充材料",
        ]
        assert [block["text"] for block in extract_call["blocks"]] == [
            "1-101、1-102 被列为文明寝室",
            "2-201 被列为文明寝室补充材料",
        ]
        assert len({block["document_id"] for block in extract_call["blocks"]}) == 2
        assert extract_call["metadata"]["document_ids"] == [
            extract_call["blocks"][0]["document_id"],
            extract_call["blocks"][1]["document_id"],
        ]

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
            "supplement.docx",
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
        assert process_steps[0]["evidence"]["texts"] == ["1-101、1-102 被列为文明寝室"]
        assert process_steps[0]["evidence"]["blocks"] == [
            {
                "document_id": extract_call["blocks"][0]["document_id"],
                "block_id": extract_call["blocks"][0]["block_id"],
                "page": 2,
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
                "reason": "模型定案后经过规则校正",
            }
        ]
        assert "读取相关字段：building" in process_steps[1]["notes"]
        assert "执行 global_lookup：补查文明寝室名单，参与最终定案。" in process_steps[1]["notes"]
        assert "执行 validation_rule：校正房间号列表，参与最终定案。" in process_steps[1]["notes"]
        assert process_steps[1]["actions"][1]["action_type"] == "global_lookup"
        assert process_steps[2]["title"] == "第三步 agent result（route 前）"
        assert process_steps[2]["value"] == "1-101,1-102"
        assert process_steps[2]["reason"] == "模型定案后经过规则校正"
        assert process_steps[3]["title"] == "第四步 route validation"
        assert process_steps[3]["status"] == "accept"
        assert process_steps[3]["route"] == "accept"
        assert process_steps[3]["needs_review"] is False
        assert process_steps[3]["reason"] == "测试 route policy 输出"
        assert steps[1]["field_decisions"][0]["actions"][1]["action_type"] == "global_lookup"
        assert steps[1]["field_decisions"][0]["actions"][1]["message"] == "补查文明寝室名单"
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
        assert agent_trace[1]["request"]["filename"] == "supplement.docx"
        assert agent_trace[1]["response"]["blocks"][0]["text"] == "2-201 被列为文明寝室补充材料"
        assert agent_trace[2]["request"]["task_spec"] == TASK_SPEC
        assert agent_trace[2]["request"]["metadata"]["document_ids"] == extract_call["metadata"]["document_ids"]
        assert agent_trace[2]["response"]["trace"]["fields"][0]["actions"][1]["action_type"] == "global_lookup"
        assert agent_trace[2]["trace"]["fields"][0]["field_name"] == "room_numbers"
        assert agent_trace[3]["request"]["field_outputs"] == [
            {"field_name": "room_numbers", "status": "resolved", "value": "1-101,1-102"}
        ]
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
                    "sample.docx",
                    b"fake docx",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
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
            "field_reference",
            "global_lookup",
            "validation_rule",
        ]
        assert handoff["fields"][0]["agent_process"]["actions"][0]["message"] == "模型请求参考字段 building"
        assert handoff["fields"][0]["agent_process"]["process_steps"][0]["stage"] == "broad_extraction"
        assert handoff["fields"][0]["agent_process"]["process_steps"][1]["actions"][1]["action_type"] == "global_lookup"
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
        assert commit["agent_process"]["reason"] == "模型定案后经过规则校正"
        assert commit["agent_process"]["actions"][1]["metadata"]["lookup_hints"] == ["文明寝室"]
        assert commit["agent_process"]["process_steps"][0]["title"] == "第一步 broad extraction"
        assert commit["agent_process"]["process_steps"][1]["title"] == "第二步 resolution / tool"
        assert commit["agent_process"]["process_steps"][2]["title"] == "第三步 agent result（route 前）"
        assert commit["agent_process"]["process_steps"][3]["title"] == "第四步 route validation"
        assert fake_agent.document_calls[0]["file_type"] == "docx"


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
        assert payload["supported_file_types"] == ["pdf", "docx"]
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
