from __future__ import annotations

import json
from typing import Any

import httpx

from backend.services.errors import AgentServiceError


class AgentClient:
    def __init__(self, *, base_url: str, timeout_seconds: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def process_document(
        self,
        *,
        file_bytes: bytes,
        filename: str,
        content_type: str | None,
        file_type: str,
    ) -> dict[str, Any]:
        files = {
            "file": (
                filename,
                file_bytes,
                content_type or "application/octet-stream",
            )
        }
        data = {"file_type": file_type}
        return self._post(
            "/v1/document-processor/process",
            files=files,
            data=data,
        )

    def extract_fields(
        self,
        *,
        html: str,
        task_spec: dict[str, Any],
        run_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result_completed: dict[str, Any] | None = None
        for event in self.extract_fields_stream(
            html=html,
            task_spec=task_spec,
            run_options=run_options,
        ):
            if event.get("type") == "result_completed":
                result_completed = event
        if result_completed is None:
            raise AgentServiceError("agent service stream ended without result_completed")
        return self._extract_result_from_stream_event(result_completed)

    def extract_fields_stream(
        self,
        *,
        html: str,
        task_spec: dict[str, Any],
        run_options: dict[str, Any] | None = None,
    ):
        payload: dict[str, Any] = {
            "documents": [
                {
                    "filename": "document.html",
                    "html": html,
                }
            ],
            "task_spec": task_spec,
        }
        if run_options is not None:
            payload["run_options"] = run_options
        url = f"{self.base_url}/v1/file-extraction-agent/extract/stream"
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                with client.stream("POST", url, json=payload) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if not line:
                            continue
                        yield json.loads(line)
        except httpx.HTTPStatusError as exc:
            exc.response.read()
            raise AgentServiceError(
                f"agent service returned {exc.response.status_code}: {exc.response.text}"
            ) from exc
        except httpx.HTTPError as exc:
            raise AgentServiceError(f"agent service request failed: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise AgentServiceError(f"agent service returned invalid stream JSON: {exc}") from exc

    def _post(self, path: str, **kwargs) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(url, **kwargs)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise AgentServiceError(
                f"agent service returned {exc.response.status_code}: {exc.response.text}"
            ) from exc
        except httpx.HTTPError as exc:
            raise AgentServiceError(f"agent service request failed: {exc}") from exc
        return response.json()

    def _extract_result_from_stream_event(self, event: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": event.get("status") or "completed",
            "failure_reason": event.get("failure_reason"),
            "result": event.get("result") or {},
            "trace": event.get("trace") or {},
        }
