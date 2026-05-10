from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.core.config import BackendSettings
from backend.main import create_app


class UnusedAgentClient:
    pass


def test_contract_nli_experiment_summary_and_sample_detail_are_served_from_backend(tmp_path: Path):
    app = create_app(
        settings=BackendSettings(database_path=tmp_path / "backend.sqlite3"),
        agent_client=UnusedAgentClient(),
    )

    with TestClient(app) as client:
        summary_response = client.get("/experiments/contract-nli")

        assert summary_response.status_code == 200
        summary = summary_response.json()
        assert summary["dataset"] == "contract_nli"
        assert summary["run_id"] == "dev_all_document_level_official_evidence_schema"
        assert summary["report"]["summary"]["agent"]["completed"] == 61
        assert summary["report"]["summary"]["direct"]["completed"] == 61
        assert summary["default_sample_id"] in {sample["sample_id"] for sample in summary["samples"]}

        detail_response = client.get(
            f"/experiments/contract-nli/samples/{summary['default_sample_id']}/detail"
        )

        assert detail_response.status_code == 200
        detail = detail_response.json()
        assert detail["summary"]["task_id"].startswith("contract-nli-")
        assert detail["summary"]["status"] == "completed"
        assert detail["result"]["fields"]
        assert detail["replay"]["actions"]
        assert any(
            action.get("tool_name") == "search_elements"
            for action in detail["replay"]["actions"]
        )
        assert detail["replay"]["display_html"]


def test_contract_nli_html_process_shows_raw_and_agent_html(tmp_path: Path):
    app = create_app(
        settings=BackendSettings(database_path=tmp_path / "backend.sqlite3"),
        agent_client=UnusedAgentClient(),
    )

    with TestClient(app) as client:
        response = client.get("/experiments/contract-nli/samples/507/html-process")

        assert response.status_code == 200
        payload = response.json()
        assert payload["sample_id"] == "507"
        assert payload["filename"].endswith(".htm")
        assert payload["raw_html_excerpt"].startswith("<HTML>")
        assert payload["agent_html_excerpt"].startswith('<h1 id="p000_b000">Contract</h1>')
        assert payload["raw_html_chars"] > payload["agent_html_chars"] / 2
        assert payload["agent_element_count"] > 1
        assert any(query["query"] == "Confidential Information" for query in payload["query_checks"])
        assert any(query["query"] == "Information" and query["match_count"] > 0 for query in payload["query_checks"])


def test_contract_nli_html_process_uses_cached_pdf_ocr_html(tmp_path: Path):
    app = create_app(
        settings=BackendSettings(database_path=tmp_path / "backend.sqlite3"),
        agent_client=UnusedAgentClient(),
    )

    with TestClient(app) as client:
        response = client.get("/experiments/contract-nli/samples/3/html-process")

        assert response.status_code == 200
        payload = response.json()
        assert payload["sample_id"] == "3"
        assert payload["filename"].endswith(".pdf")
        assert payload["source_kind"] == "pdf-ocr"
        assert payload["agent_html_excerpt"].startswith('<section class="page"')
        assert payload["agent_html"].startswith('<section class="page"')
        assert payload["display_html"].startswith("<!doctype html>")
        assert len(payload["agent_html"]) > len(payload["agent_html_excerpt"])
        assert len(payload["display_html"]) > len(payload["display_html_excerpt"])
        assert payload["agent_element_count"] >= 80
        assert payload["ocr_block_count"] >= 80
        assert any(query["query"] == "Confidential Information" and query["match_count"] > 0 for query in payload["query_checks"])


def test_contract_nli_pdf_detail_uses_ocr_trace_evidence_ids(tmp_path: Path):
    app = create_app(
        settings=BackendSettings(database_path=tmp_path / "backend.sqlite3"),
        agent_client=UnusedAgentClient(),
    )

    with TestClient(app) as client:
        response = client.get("/experiments/contract-nli/samples/3/detail")

        assert response.status_code == 200
        payload = response.json()
        search_actions = [
            action
            for action in payload["replay"]["actions"]
            if action.get("tool_name") == "search_elements"
        ]
        assert search_actions
        first_matches = search_actions[0]["result"]["matches"]
        assert first_matches
        assert first_matches[0]["element_id"] != "p001_b000"
