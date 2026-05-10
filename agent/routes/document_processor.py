"""把 PDF 转 HTML 业务入口适配成 HTTP endpoints。"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
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
    engine: str


class ProcessResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    filename: str
    html: str
    display_html: str | None = None
    markdown: str = ""
    md_list: list[str] = Field(default_factory=list)
    blocks: list[dict[str, Any]] = Field(default_factory=list)
    semantic_document: dict[str, Any] = Field(default_factory=dict)
    meta_info: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/v1/ocr/capabilities", response_model=CapabilitiesResponse)
async def get_capabilities() -> CapabilitiesResponse:
    return CapabilitiesResponse(
        supported_file_types=["pdf"],
        implemented_file_types=["pdf"],
        engine="mineru-pipeline",
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


def _process_document(file_obj, file_type: str | None):
    process_document = import_module("service.document_processor.processor").process
    return process_document(file_obj, file_type)


def _build_process_response(result) -> ProcessResponse:
    return ProcessResponse(
        filename=result.filename,
        html=result.html,
        display_html=result.display_html,
        markdown=result.markdown,
        md_list=result.md_list,
        blocks=result.blocks,
        semantic_document=result.semantic_document,
        meta_info=result.meta_info,
        warnings=result.warnings,
    )
