"""Adapt public document QA completion inputs into internal graph input."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from service.file_extraction_agent.impl.html_index import DocumentFileTree, materialize_tree
from service.file_extraction_agent.impl.html_state import DocumentQaCompletionInput
from service.file_extraction_agent.schemas import (
    DocumentQaMessage,
    InputDocument,
    RunOptions,
)

DEFAULT_WORKSPACE_ROOT = os.getenv(
    "FILE_EXTRACTION_AGENT_WORKSPACE_ROOT",
    str(Path(__file__).resolve().parents[2] / "data" / "qa_workspace"),
)


def build_completion_input(
    *,
    completion_id: str,
    documents: Any,
    messages: Any,
    run_options: Any = None,
    workspace_root: str | Path | None = None,
) -> DocumentQaCompletionInput:
    if not isinstance(completion_id, str) or not completion_id.strip():
        raise ValueError("completion_id is required")
    normalized_documents = normalize_documents(documents)
    normalized_messages = normalize_messages(messages)
    normalized_run_options = normalize_run_options(run_options)
    resolved_root = _resolve_workspace_root(workspace_root, normalized_run_options)
    document = materialize_tree(
        [item.model_dump() for item in normalized_documents],
        Path(resolved_root) / completion_id,
    )
    return DocumentQaCompletionInput(
        completion_id=completion_id,
        documents=normalized_documents,
        messages=normalized_messages,
        document=document,
        run_options=normalized_run_options,
    )


def _resolve_workspace_root(explicit: str | Path | None, run_options: RunOptions) -> Path:
    if explicit is not None:
        return Path(explicit)
    if run_options.workspace_root:
        return Path(run_options.workspace_root)
    return Path(DEFAULT_WORKSPACE_ROOT)


def normalize_documents(documents: Any) -> list[InputDocument]:
    if not isinstance(documents, list) or not documents:
        raise ValueError("documents must be a non-empty list")
    normalized: list[InputDocument] = []
    for index, item in enumerate(documents, start=1):
        if isinstance(item, InputDocument):
            document = item
        elif isinstance(item, dict):
            document = InputDocument(**item)
        else:
            document = InputDocument(
                filename=getattr(item, "filename", ""),
                html=getattr(item, "html", ""),
            )
        if not document.filename.strip():
            raise ValueError(f"documents[{index}].filename is required")
        if not document.html.strip():
            raise ValueError(f"documents[{index}].html must be a non-empty string")
        normalized.append(document)
    return normalized


def normalize_messages(messages: Any) -> list[DocumentQaMessage]:
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages must be a non-empty list")
    normalized: list[DocumentQaMessage] = []
    for item in messages:
        if isinstance(item, DocumentQaMessage):
            normalized.append(item)
        elif isinstance(item, dict):
            normalized.append(DocumentQaMessage(**item))
        else:
            normalized.append(
                DocumentQaMessage(
                    role=getattr(item, "role", "user"),
                    content=getattr(item, "content", ""),
                    tool_calls=getattr(item, "tool_calls", None),
                    tool_call_id=getattr(item, "tool_call_id", None),
                    name=getattr(item, "name", None),
                )
            )
    return normalized


def normalize_run_options(run_options: Any) -> RunOptions:
    if run_options is None:
        options = RunOptions()
    elif isinstance(run_options, RunOptions):
        options = run_options
    elif isinstance(run_options, dict):
        options = RunOptions(**run_options)
    else:
        options = RunOptions(max_tool_calls=getattr(run_options, "max_tool_calls", RunOptions().max_tool_calls))
    if options.max_tool_calls <= 0:
        raise ValueError("max_tool_calls must be positive")
    return options


__all__ = [
    "build_completion_input",
    "normalize_documents",
    "normalize_messages",
    "normalize_run_options",
]
