"""Adapt public document QA completion inputs into internal graph input."""

from __future__ import annotations

from typing import Any

from service.file_extraction_agent.impl.html_index import build_html_document
from service.file_extraction_agent.impl.html_state import DocumentQaCompletionInput
from service.file_extraction_agent.schemas import (
    DocumentQaMemory,
    DocumentQaMessage,
    InputDocument,
    RunOptions,
)


def build_completion_input(
    *,
    completion_id: str,
    documents: Any,
    messages: Any,
    memory: Any = None,
    run_options: Any = None,
) -> DocumentQaCompletionInput:
    if not isinstance(completion_id, str) or not completion_id.strip():
        raise ValueError("completion_id is required")
    normalized_documents = normalize_documents(documents)
    normalized_messages = normalize_messages(messages)
    normalized_memory = normalize_memory(memory)
    normalized_run_options = normalize_run_options(run_options)
    document = build_html_document([item.model_dump() for item in normalized_documents])
    return DocumentQaCompletionInput(
        completion_id=completion_id,
        documents=normalized_documents,
        messages=normalized_messages,
        memory=normalized_memory,
        document=document,
        run_options=normalized_run_options,
    )


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


def normalize_memory(memory: Any) -> DocumentQaMemory:
    if memory is None:
        return DocumentQaMemory()
    if isinstance(memory, DocumentQaMemory):
        return memory
    if isinstance(memory, dict):
        return DocumentQaMemory(**memory)
    return DocumentQaMemory(
        reading_history=list(getattr(memory, "reading_history", []) or []),
        evidence_notes=list(getattr(memory, "evidence_notes", []) or []),
        prior_answers=list(getattr(memory, "prior_answers", []) or []),
        open_threads=list(getattr(memory, "open_threads", []) or []),
    )


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
    "normalize_memory",
    "normalize_run_options",
]
