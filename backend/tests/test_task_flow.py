from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from backend.core.config import BackendSettings
from backend.main import create_app
from backend.services.agent_process import build_field_agent_process
from backend.services.task_service import sanitize_replay_display_html


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
    def __init__(self):
        self.document_calls: list[dict[str, Any]] = []
        self.extraction_calls: list[dict[str, Any]] = []

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
        display_html = (
            "<!doctype html><html><head>"
            "<style>.page-number { color: #737373; }</style>"
            "</head><body>"
            '<section class="page" id="page_001" data-page="1">'
            '<div class="page-number">Page 1</div>'
            f'<h1 id="dp-h1-1">测试文档</h1><p id="dp-p-1">{text}</p>'
            '<div id="dp-footer-1" class="block block-page_footer" data-type="page_footer">428249v2</div>'
            "</section>"
            '<section class="page" id="page_002" data-page="2">'
            '<div class="page-number">Page 2</div>'
            '<div id="dp-header-2" data-type="page_header">Page 2</div>'
            "</section>"
            "</body></html>"
        )
        return {
            "file_type": file_type,
            "filename": filename,
            "html": f'<h1 id="dp-h1-1">测试文档</h1><p id="dp-p-1">{text}</p>',
            "display_html": display_html,
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
                "source_selectors": {"0001.0001.0001": "dp-p-1"},
                "actions": [
                    {
                        "tool_name": "read",
                        "reason": "旧工具文字不应出现在 replay action",
                        "args": {"path_id": "evidence://0001.0001.0001"},
                        "result": {"ok": True},
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


class FakeMissingRequiredFieldClient(FakeAgentClient):
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


def build_app(tmp_path: Path):
    fake_agent = FakeAgentClient()
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
    app, fake_agent = build_app(tmp_path)

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


def test_list_tasks_returns_latest_db_tasks_for_workspace(tmp_path: Path):
    app, _fake_agent = build_app(tmp_path)

    with TestClient(app) as client:
        first_response = client.post(
            "/tasks",
            data={
                "task_type": "contract_nli",
                "task_spec": json.dumps(TASK_SPEC, ensure_ascii=False),
                "metadata": json.dumps({"sample_id": "27"}, ensure_ascii=False),
            },
            files={"file": ("sample-27.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )
        second_response = client.post(
            "/tasks",
            data={
                "task_type": "contract_nli",
                "task_spec": json.dumps(TASK_SPEC, ensure_ascii=False),
                "metadata": json.dumps({"sample_id": "72"}, ensure_ascii=False),
            },
            files={"file": ("sample-72.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )

        assert first_response.status_code == 200
        assert second_response.status_code == 200

        list_response = client.get("/tasks")
        assert list_response.status_code == 200
        payload = list_response.json()

        task_ids = [task["task_id"] for task in payload["tasks"]]
        assert task_ids[:2] == [
            second_response.json()["task_id"],
            first_response.json()["task_id"],
        ]
        assert payload["tasks"][0]["status"] == "completed"
        assert "route" not in payload["tasks"][0]
        assert "route_reason" not in payload["tasks"][0]
        assert payload["tasks"][0]["has_result"] is True
        assert payload["tasks"][0]["has_trace"] is True
        assert "needs_review" not in payload["tasks"][0]


def test_create_task_commits_resolved_agent_fields_without_routing(tmp_path: Path):
    app, fake_agent = build_app(tmp_path)

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
        assert "needs_review" not in task_summary
        assert "route" not in task_summary
        assert "route_reason" not in task_summary

        result_response = client.get(f"/tasks/{task_id}/result")
        assert result_response.status_code == 200
        result_payload = result_response.json()
        assert "route" not in result_payload
        result_field = result_payload["fields"][0]
        assert result_field["field_name"] == "room_numbers"
        assert result_field["agent_value"] == "1-101,1-102"
        assert result_field["final_value"] == "1-101,1-102"
        assert result_field["source"] == "agent"
        assert result_field["committed"] is True
        assert "route" not in result_field

        audit_response = client.get(f"/tasks/{task_id}/audit")
        assert audit_response.status_code == 200
        commit = audit_response.json()["field_commits"][0]
        assert commit["field_name"] == "room_numbers"
        assert "route" not in commit
        assert "reviewed" not in commit
        assert "review_decision" not in commit
        assert "review_value" not in commit
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
        assert "测试文档" in replay["display_html"]
        assert "Page 1" not in replay["display_html"]
        assert "Page 2" not in replay["display_html"]
        assert "428249v2" not in replay["display_html"]
        assert "page-number" not in replay["display_html"]
        assert "page_footer" not in replay["display_html"]
        assert 'id="0001.0001.0001"' in replay["display_html"]
        assert 'data-element-id="0001.0001.0001"' in replay["display_html"]
        assert 'id="dp-p-1"' not in replay["display_html"]
        assert replay["source_selectors"] == {"0001.0001.0001": "0001.0001.0001"}
        assert replay["actions"] == [
            {
                "tool_name": "read",
                "args": {"path_id": "evidence://0001.0001.0001"},
                "result": {"ok": True},
            }
        ]

        extract_call = fake_agent.extraction_calls[0]
        assert extract_call["task_spec"] == TASK_SPEC
        assert "dp-p-1" in extract_call["html"]


def test_replay_uses_live_source_index_before_extraction_finishes(tmp_path: Path):
    app, _fake_agent = build_app(tmp_path)

    with TestClient(app) as client:
        service = app.state.task_service
        upload = service.upload_file_payload(
            file_bytes=b"%PDF-1.4 fake",
            filename="sample.pdf",
            content_type="application/pdf",
        )
        created = service.create_task(
            files=[upload],
            task_type="civilized_dormitory",
            task_spec=TASK_SPEC,
            metadata={},
            run_pipeline=False,
        )
        task_id = created["task_id"]
        task = service.get_task_or_raise(task_id)
        service._save_agent_stage_run(
            task_id=task_id,
            sequence=1,
            stage="document_processing",
            agent_name="document_processor",
            status="completed",
            failure_reason=None,
            request={"filename": "sample.pdf"},
            response={
                "filename": "sample.pdf",
                "html": '<h1 id="dp-h1-1">测试文档</h1><p id="dp-p-1">1-101 被列为文明寝室</p>',
                "display_html": '<main><h1 id="dp-h1-1">测试文档</h1><p id="dp-p-1">1-101 被列为文明寝室</p></main>',
            },
            trace={},
            started_at=task["created_at"],
            finished_at=task["created_at"],
        )
        service._emit_task_event(
            task,
            event_type="agent.event",
            payload={
                "agent": "file_extraction_agent",
                "type": "source_indexed",
                "tool": "source_index",
                "result": {
                    "ok": True,
                    "document_tree": "/\n└── 0001 sample.pdf/",
                    "source_selectors": {"0001.0000.0001": "dp-p-1"},
                },
            },
            now=task["created_at"],
        )

        replay_response = client.get(f"/tasks/{task_id}/replay")

    assert replay_response.status_code == 200
    replay = replay_response.json()
    assert replay["outline_tree"] == "/\n└── 0001 sample.pdf/"
    assert replay["source_selectors"] == {"0001.0000.0001": "0001.0000.0001"}
    assert 'id="0001.0000.0001"' in replay["display_html"]
    assert 'data-element-id="0001.0000.0001"' in replay["display_html"]
    assert 'id="dp-p-1"' not in replay["display_html"]


def test_replay_display_html_sanitizer_keeps_large_css_fast():
    large_css = (".not-target " + ("x" * 20) + " ") * 700
    no_target_html = f"<style>{large_css}</style><body><p>正文内容</p></body>"

    started_at = time.perf_counter()
    sanitized = sanitize_replay_display_html(no_target_html)
    elapsed = time.perf_counter() - started_at

    assert elapsed < 0.2
    assert "正文内容" in sanitized
    assert ".not-target" in sanitized

    chrome_html = (
        "<!doctype html><html><head><style>"
        ".page-number { color: #737373; }"
        ".block-page_footer { color: #999; }"
        ".content { font-weight: 600; }"
        "</style></head><body>"
        '<div class="page-number">Page 1</div>'
        '<p id="dp-p-1">正文内容</p>'
        '<div class="block-page_footer" data-type="page_footer">428249v2</div>'
        "</body></html>"
    )

    sanitized = sanitize_replay_display_html(chrome_html)

    assert "正文内容" in sanitized
    assert ".content" in sanitized
    assert "Page 1" not in sanitized
    assert "428249v2" not in sanitized
    assert "page-number" not in sanitized
    assert "block-page_footer" not in sanitized


def test_create_task_accepts_multiple_files_and_merges_document_blocks(tmp_path: Path):
    app, fake_agent = build_app(tmp_path)

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
        assert process_steps[2]["title"] == "第三步 agent result"
        assert process_steps[2]["value"] == "1-101,1-102"
        assert process_steps[2]["reason"] == "候选证据支持字段值"
        assert steps[1]["field_decisions"][0]["actions"][1]["action_type"] == "add_broad_candidate"
        assert steps[1]["field_decisions"][0]["actions"][1]["message"] == "召回文明寝室房间号候选"
        trace_field = trace_response.json()["fields"][0]
        assert trace_field["process_steps"][0]["stage"] == "broad_extraction"
        assert trace_field["process_steps"][1]["stage"] == "field_resolution"
        assert trace_field["process_steps"][2]["stage"] == "final_result"
        assert len(trace_field["process_steps"]) == 3

        agent_trace = trace_response.json()["agent_trace"]
        assert [event["agent"] for event in agent_trace] == [
            "document_processor",
            "document_processor",
            "file_extraction_agent",
        ]
        assert [event["sequence"] for event in agent_trace] == [1, 2, 3]
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


def test_missing_required_field_placeholder_stays_uncommitted_without_routing(tmp_path: Path):
    fake_agent = FakeMissingRequiredFieldClient()
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
        assert task_summary["status"] == "completed"
        assert task_summary["stage"] == "done"
        assert "route" not in task_summary
        assert "needs_review" not in task_summary

        unavailable_response = client.get(f"/tasks/{task_id}/manual-check")
        assert unavailable_response.status_code == 404

        submit_response = client.post(
            f"/tasks/{task_id}/manual-check",
            json={
                "decision": "revise_and_approve",
                "fields": [
                    {
                        "field_name": "room_numbers",
                        "manual_value": "1-101",
                    }
                ],
                "comment": "人工补录 required 字段",
                "operator": "teacher",
            },
        )
        assert submit_response.status_code == 404

        result_field = client.get(f"/tasks/{task_id}/result").json()["fields"][0]
        assert result_field["agent_value"] is None
        assert result_field["final_value"] is None
        assert result_field["source"] == "none"
        assert result_field["committed"] is False


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


def test_capabilities_returns_supported_task_features_without_routing(tmp_path: Path):
    app, _fake_agent = build_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/capabilities")

        assert response.status_code == 200
        payload = response.json()
        assert payload["supported_file_types"] == ["pdf"]
        assert payload["task_types"] == []
        assert "routes" not in payload
        assert "review_decisions" not in payload
        assert payload["features"] == {
            "trace": True,
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
