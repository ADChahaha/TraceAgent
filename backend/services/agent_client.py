from __future__ import annotations

import json
from typing import Any

import httpx

from backend.services.errors import AgentServiceError


class AgentClient:
    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float = 60.0,
        cancel_timeout_seconds: float = 2.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.cancel_timeout_seconds = cancel_timeout_seconds

    def process_document(
        self,
        *,
        file_bytes: bytes,
        filename: str,
        content_type: str | None,
        file_type: str,
    ) -> dict[str, Any]:
        normalized_file_type = str(file_type).strip().lower().lstrip(".")
        endpoint_by_file_type = {
            "pdf": "/v1/document-processor/process",
            "docx": "/v1/document-processor/docx/process",
        }
        endpoint = endpoint_by_file_type.get(normalized_file_type)
        if endpoint is None:
            raise ValueError(f"Unsupported file type: {file_type!r}")

        files = {
            "file": (
                filename,
                file_bytes,
                content_type or "application/octet-stream",
            )
        }
        data = {"file_type": normalized_file_type}
        return self._post(
            endpoint,
            files=files,
            data=data,
        )

    def create_document_qa_completion_stream(
        self,
        *,
        completion_id: str,
        documents: list[dict[str, Any]],
        messages: list[dict[str, str]],
        memory: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        run_options: dict[str, Any] | None = None,
    ):
        payload: dict[str, Any] = {
            "completion_id": completion_id,
            "documents": documents,
            "messages": messages,
            "memory": memory,
            "stream": True,
            "metadata": metadata or {},
        }
        if run_options is not None:
            payload["run_options"] = run_options
        url = f"{self.base_url}/v1/document-qa/chat/completions"
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                with client.stream("POST", url, json=payload) as response:
                    response.raise_for_status()
                    yield from _iter_sse_payloads(response)
        except httpx.HTTPStatusError as exc:
            exc.response.read()
            raise AgentServiceError(
                f"agent service returned {exc.response.status_code}: {exc.response.text}"
            ) from exc
        except httpx.HTTPError as exc:
            raise AgentServiceError(f"agent service request failed: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise AgentServiceError(f"agent service returned invalid SSE JSON: {exc}") from exc

    def cancel_document_qa_completion(self, completion_id: str) -> dict[str, Any]:
        return self._post(
            f"/v1/document-qa/chat/completions/{completion_id}/cancel",
            timeout_seconds=self.cancel_timeout_seconds,
        )

    def _post(self, path: str, *, timeout_seconds: float | None = None, **kwargs) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            with httpx.Client(timeout=timeout_seconds or self.timeout_seconds) as client:
                response = client.post(url, **kwargs)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise AgentServiceError(
                f"agent service returned {exc.response.status_code}: {exc.response.text}"
            ) from exc
        except httpx.HTTPError as exc:
            raise AgentServiceError(f"agent service request failed: {exc}") from exc
        return response.json()


def _iter_sse_payloads(response: httpx.Response):
    event_lines: list[str] = []
    for line in response.iter_lines():
        if line == "":
            payload = _parse_sse_payload(event_lines)
            event_lines = []
            if payload is not None:
                yield payload
            continue
        event_lines.append(line)
    payload = _parse_sse_payload(event_lines)
    if payload is not None:
        yield payload


def _parse_sse_payload(lines: list[str]) -> dict[str, Any] | None:
    data_lines = [line.removeprefix("data: ") for line in lines if line.startswith("data: ")]
    if not data_lines:
        return None
    return json.loads("\n".join(data_lines))
