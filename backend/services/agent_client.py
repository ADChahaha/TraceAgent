from __future__ import annotations

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
        blocks: list[dict[str, Any]],
        markdown: str,
        md_list: list[str],
        task_spec: dict[str, Any],
        metadata: dict[str, Any],
        run_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "blocks": blocks,
            "markdown": markdown,
            "md_list": md_list,
            "task_spec": task_spec,
            "metadata": metadata,
        }
        if run_options is not None:
            payload["run_options"] = run_options
        return self._post("/v1/file-extraction-agent/extract", json=payload)

    def evaluate_route_policy(
        self,
        *,
        task_spec: dict[str, Any],
        field_outputs: list[dict[str, Any]],
        refs_with_text: list[dict[str, Any]],
        metadata: dict[str, Any],
        policy_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "task_spec": task_spec,
            "field_outputs": field_outputs,
            "refs_with_text": refs_with_text,
            "metadata": metadata,
        }
        if policy_options is not None:
            payload["policy_options"] = policy_options
        return self._post("/v1/route-policy-agent/evaluate", json=payload)

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

