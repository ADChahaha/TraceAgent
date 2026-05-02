"""把 PDF 转 HTML 业务入口适配成 HTTP endpoints。"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict
from starlette.concurrency import run_in_threadpool

from service.document_processor.processor import (
    InvalidFileObjectError,
    UnsupportedFileTypeError,
)

router = APIRouter(tags=["document-processor"])


@dataclass(slots=True)
class UploadFileProxy:
    filename: str | None
    content_type: str | None
    file: Any

    def read(self, *args, **kwargs):
        return self.file.read(*args, **kwargs)

    def seek(self, *args, **kwargs):
        return self.file.seek(*args, **kwargs)

    def tell(self):
        return self.file.tell()


class HealthResponse(BaseModel):
    status: str


class CapabilitiesResponse(BaseModel):
    supported_file_types: list[str]
    implemented_file_types: list[str]
    docling_artifacts_path: str | None = None
    docling_artifacts_available: bool


class ProcessResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    filename: str
    html: str


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/v1/ocr/capabilities", response_model=CapabilitiesResponse)
async def get_capabilities() -> CapabilitiesResponse:
    artifacts_path = _resolve_docling_artifacts_path()
    return CapabilitiesResponse(
        supported_file_types=["pdf"],
        implemented_file_types=["pdf"],
        docling_artifacts_path=_stringify_path(artifacts_path),
        docling_artifacts_available=bool(artifacts_path and artifacts_path.exists()),
    )


@router.post("/v1/document-processor/process", response_model=ProcessResponse)
@router.post("/v1/ocr/process", response_model=ProcessResponse)
async def process_document(
    file: UploadFile = File(...),
    file_type: str | None = Form(default=None),
) -> ProcessResponse:
    await file.seek(0)
    file_proxy = UploadFileProxy(
        filename=file.filename,
        content_type=file.content_type,
        file=file.file,
    )
    try:
        result = await run_in_threadpool(_process_document, file_proxy, file_type)
    except (InvalidFileObjectError, UnsupportedFileTypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    return _build_process_response(result)


def _stringify_path(path: Path | None) -> str | None:
    if path is None:
        return None
    return str(path)


def _resolve_docling_artifacts_path() -> Path | None:
    docling_converter = import_module("service.document_processor.docling_converter")
    return docling_converter.resolve_docling_artifacts_path()


def _process_document(file_obj, file_type: str | None):
    process_document = import_module("service.document_processor.processor").process
    return process_document(file_obj, file_type)


def _build_process_response(result) -> ProcessResponse:
    return ProcessResponse(
        filename=result.filename,
        html=result.html,
    )
