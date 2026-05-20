from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from backend.core.config import BackendSettings
from backend.crud import tasks as tasks_crud
from backend.main import create_app
from backend.services.time_utils import utc_now


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
    def process_document(
        self,
        *,
        file_bytes: bytes,
        filename: str,
        content_type: str | None,
        file_type: str,
    ) -> dict[str, Any]:
        return {
            "file_type": file_type,
            "filename": filename,
            "html": '<h1 id="title">测试文档</h1><p id="p1">1-101 被列为文明寝室</p>',
            "display_html": "<html><body><p>1-101 被列为文明寝室</p></body></html>",
            "markdown": "1-101 被列为文明寝室",
            "md_list": ["1-101 被列为文明寝室"],
            "blocks": [
                {
                    "text": "1-101 被列为文明寝室",
                    "page_no": 1,
                    "kind": "text",
                    "meta_info": {},
                }
            ],
            "meta_info": {},
            "warnings": [],
        }

    def extract_fields(
        self,
        *,
        html: str,
        task_spec: dict[str, Any],
        run_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ref = {"document_id": "doc_test", "page": 1, "block_id": "p1"}
        return {
            "status": "completed",
            "failure_reason": None,
            "result": {
                "fields": [
                    {
                        "field_name": "room_numbers",
                        "status": "resolved",
                        "value": "1-101",
                    }
                ]
            },
            "trace": {
                "actions": [
                    {
                        "tool_name": "tree",
                        "args": {"path_id": "evidence://0000"},
                        "reason": "查看目录",
                    },
                    {
                        "tool_name": "write_field",
                        "args": {"field_id": "room_numbers", "value": "1-101"},
                        "reason": "写入字段",
                    },
                ],
                "fields": [
                    {
                        "field_name": "room_numbers",
                        "status": "resolved",
                        "evidence": {
                            "texts": ["1-101 被列为文明寝室"],
                            "refs": [ref],
                        },
                        "related_fields": [],
                        "actions": [
                            {
                                "tool_name": "write_field",
                                "args": {"field_id": "room_numbers", "value": "1-101"},
                                "reason": "写入字段",
                            }
                        ],
                        "reason": "证据支持字段值",
                        "failure_reason": None,
                    }
                ],
            },
        }


def build_app(tmp_path: Path):
    app = create_app(
        settings=BackendSettings(database_path=tmp_path / "backend.sqlite3"),
        agent_client=FakeAgentClient(),
    )
    return app


def create_task(client: TestClient) -> str:
    response = client.post(
        "/tasks",
        data={
            "task_type": "civilized_dormitory",
            "task_spec": json.dumps(TASK_SPEC, ensure_ascii=False),
        },
        files={"file": ("sample.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["stream"]["state"] == "running"
    assert payload["stream"]["last_event_seq"] == 1
    return payload["task_id"]


def test_task_summary_includes_stream_cursor_after_pipeline_finishes(tmp_path: Path):
    app = build_app(tmp_path)

    with TestClient(app) as client:
        task_id = create_task(client)

        summary_response = client.get(f"/tasks/{task_id}")

    assert summary_response.status_code == 200
    summary = summary_response.json()
    assert summary["status"] == "completed"
    assert summary["stage"] == "done"
    assert summary["stream"]["state"] == "ended"
    assert summary["stream"]["last_event_seq"] >= 6


def test_task_events_endpoint_replays_persisted_events_and_respects_after_seq(tmp_path: Path):
    app = build_app(tmp_path)

    with TestClient(app) as client:
        task_id = create_task(client)

        replay_response = client.get(f"/tasks/{task_id}/events?after_seq=0")
        replay_lines = [
            line.removeprefix("data: ")
            for line in replay_response.text.splitlines()
            if line.startswith("data: ")
        ]
        replay_events = [json.loads(line) for line in replay_lines]
        second_seq = replay_events[1]["seq"]

        resume_response = client.get(f"/tasks/{task_id}/events?after_seq={second_seq}")
        resume_lines = [
            line.removeprefix("data: ")
            for line in resume_response.text.splitlines()
            if line.startswith("data: ")
        ]
        resume_events = [json.loads(line) for line in resume_lines]

    assert replay_response.status_code == 200
    assert replay_response.headers["content-type"].startswith("text/event-stream")
    assert [event["seq"] for event in replay_events] == list(range(1, len(replay_events) + 1))
    assert replay_events[0]["type"] == "task.created"
    assert "task.completed" in [event["type"] for event in replay_events]
    assert all(event["seq"] > second_seq for event in resume_events)
    assert resume_events[0]["seq"] == second_seq + 1


def test_task_events_endpoint_waits_for_new_events_until_task_ends(tmp_path: Path):
    app = build_app(tmp_path)

    with TestClient(app) as client:
        task = client.app.state.task_service.create_task(
            files=[
                client.app.state.task_service.upload_file_payload(
                    file_bytes=b"%PDF-1.4 fake",
                    filename="sample.pdf",
                    content_type="application/pdf",
                )
            ],
            task_type="civilized_dormitory",
            task_spec=TASK_SPEC,
            metadata={},
            run_pipeline=False,
        )
        task_id = task["task_id"]

        def finish_task_later():
            time.sleep(0.1)
            service = client.app.state.task_service
            finished_at = utc_now()
            finished_task = tasks_crud.update_task(
                service.connection,
                task_id=task_id,
                status="completed",
                stage="done",
                completed_at=finished_at,
                now=finished_at,
            )
            service._emit_task_event(
                finished_task,
                event_type="task.completed",
                payload={},
                now=finished_at,
            )

        thread = threading.Thread(target=finish_task_later)
        thread.start()
        response = client.get(f"/tasks/{task_id}/events?after_seq=1")
        thread.join(timeout=2)

    lines = [
        line.removeprefix("data: ")
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    events = [json.loads(line) for line in lines]
    assert response.status_code == 200
    assert events[-1]["type"] == "task.completed"


def test_removed_manual_check_endpoint_is_not_available_and_does_not_append_events(tmp_path: Path):
    app = build_app(tmp_path)

    with TestClient(app) as client:
        task_id = create_task(client)
        summary_response = client.get(f"/tasks/{task_id}")
        assert summary_response.json()["status"] == "completed"
        assert summary_response.json()["stage"] == "done"
        last_seq = summary_response.json()["stream"]["last_event_seq"]

        unavailable_response = client.post(
            f"/tasks/{task_id}/manual-check",
            json={
                "decision": "revise_and_approve",
                "fields": [
                    {
                        "field_name": "room_numbers",
                        "manual_value": "1-101",
                    }
                ],
            },
        )
        events_response = client.get(f"/tasks/{task_id}/events?after_seq={last_seq}")
        all_events_response = client.get(f"/tasks/{task_id}/events?after_seq=0")

    lines = [
        line.removeprefix("data: ")
        for line in events_response.text.splitlines()
        if line.startswith("data: ")
    ]
    events = [json.loads(line) for line in lines]
    assert unavailable_response.status_code == 404
    assert events == []

    all_lines = [
        line.removeprefix("data: ")
        for line in all_events_response.text.splitlines()
        if line.startswith("data: ")
    ]
    all_events = [json.loads(line) for line in all_lines]
    assert all_events[-1]["type"] == "task.completed"
    assert "route" not in all_events[-1]["payload"]
