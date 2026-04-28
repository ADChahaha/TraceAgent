from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from backend.core.config import BackendSettings
from backend.main import create_app


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
        return {
            "file_type": file_type,
            "filename": filename,
            "markdown": "1-101、1-102 被列为文明寝室",
            "md_list": ["1-101、1-102 被列为文明寝室"],
            "blocks": [
                {
                    "text": "1-101、1-102 被列为文明寝室",
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


def build_app(tmp_path: Path, route: str = "accept"):
    fake_agent = FakeAgentClient(route=route)
    app = create_app(
        settings=BackendSettings(database_path=tmp_path / "backend.sqlite3"),
        agent_client=fake_agent,
    )
    return app, fake_agent


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
        assert created["status"] == "completed"
        assert created["stage"] == "done"

        task_id = created["task_id"]
        task_response = client.get(f"/tasks/{task_id}")
        assert task_response.status_code == 200
        assert task_response.json()["needs_review"] is False
        assert task_response.json()["route"] == "accept"

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
        assert commit["used_validation_rule"] is True
        assert commit["committed_by"] == "agent"

        extract_call = fake_agent.extraction_calls[0]
        assert extract_call["task_spec"] == TASK_SPEC
        assert extract_call["blocks"][0]["document_id"].startswith("doc_")
        assert extract_call["blocks"][0]["block_id"].startswith("doc_")
        route_call = fake_agent.route_policy_calls[0]
        assert route_call["field_outputs"] == [
            {"field_name": "room_numbers", "status": "resolved", "value": "1-101,1-102"}
        ]
        assert route_call["refs_with_text"][0]["refs"][0]["text"] == "1-101、1-102 被列为文明寝室"


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
        assert created["status"] == "waiting_review"
        assert created["stage"] == "review"
        task_id = created["task_id"]

        review_response = client.get(f"/tasks/{task_id}/review")
        assert review_response.status_code == 200
        handoff = review_response.json()
        assert handoff["route"] == "review"
        assert handoff["fields"][0]["needs_review"] is True
        assert handoff["fields"][0]["evidence_texts"] == ["1-101、1-102 被列为文明寝室"]
        assert handoff["fields"][0]["actions"] == ["validation_rule"]

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
        assert fake_agent.document_calls[0]["file_type"] == "docx"


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
