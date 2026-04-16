from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from ocr_processor.impl.base import InvalidFileObjectError
from ocr_processor.types import FileType, UnsupportedFileTypeError

router = APIRouter(tags=["ocr-processor"])


@dataclass(slots=True)
class UploadFileProxy:
    filename: str | None
    content_type: str | None
    file: Any


class HealthResponse(BaseModel):
    status: str


class CapabilitiesResponse(BaseModel):
    supported_file_types: list[str]
    implemented_file_types: list[str]
    docling_artifacts_path: str | None = None
    docling_artifacts_available: bool


class BoundingBoxResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    x0: float
    y0: float
    x1: float
    y1: float


class ContentBlockResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    text: str
    page_no: int | None = None
    bbox: BoundingBoxResponse | None = None
    kind: str = "text"
    meta_info: dict[str, Any] = Field(default_factory=dict)


class ProcessResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    file_type: FileType
    filename: str | None
    md_list: list[str] = Field(default_factory=list)
    markdown: str = ""
    blocks: list[ContentBlockResponse] = Field(default_factory=list)
    meta_info: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/v1/ocr/capabilities", response_model=CapabilitiesResponse)
async def get_capabilities() -> CapabilitiesResponse:
    artifacts_path = _resolve_docling_artifacts_path()
    return CapabilitiesResponse(
        supported_file_types=[item.value for item in FileType],
        implemented_file_types=[FileType.PDF.value, FileType.DOCX.value],
        docling_artifacts_path=_stringify_path(artifacts_path),
        docling_artifacts_available=bool(artifacts_path and artifacts_path.exists()),
    )


@router.post("/v1/ocr/process", response_model=ProcessResponse)
async def process_ocr(
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
    pdf_docling_adapter = import_module("ocr_processor.impl.pdf.docling_adapter")
    return pdf_docling_adapter.resolve_docling_artifacts_path()


def _process_document(file_obj, file_type: str | None):
    process_document = import_module("ocr_processor.processor").process
    return process_document(file_obj, file_type)


def _build_process_response(result) -> ProcessResponse:
    return ProcessResponse(
        file_type=result.file_type,
        filename=result.filename,
        md_list=list(result.md_list),
        markdown=result.markdown,
        blocks=[_build_block_response(block) for block in result.blocks],
        meta_info=dict(result.meta_info),
        warnings=list(result.warnings),
    )


def _build_block_response(block) -> ContentBlockResponse:
    return ContentBlockResponse(
        text=block.text,
        page_no=block.page_no,
        bbox=_build_bbox_response(block.bbox),
        kind=block.kind,
        meta_info=dict(block.meta_info),
    )


def _build_bbox_response(bbox) -> BoundingBoxResponse | None:
    if bbox is None:
        return None

    return BoundingBoxResponse(
        x0=bbox.x0,
        y0=bbox.y0,
        x1=bbox.x1,
        y1=bbox.y1,
    )
