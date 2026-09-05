"""上传文件 → 解析 HTML → 文档树和索引 → 返回完整资源路径与原文。"""

from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from service.document_processor import processor
from service.document_resources import prepare_resources
from service.document_resources.schemas import InputDocument


router = APIRouter(tags=["document-resources"])


@dataclass
class UploadFileProxy:
    filename: str
    file: Any

    def read(self, *args):
        return self.file.read(*args)

    def seek(self, *args):
        return self.file.seek(*args)


class ResourceResponse(BaseModel):
    resource_path: str
    documents: list[InputDocument]


@router.get("/healthz")
async def healthz():
    return {"status": "ok"}


@router.get("/v1/ocr/capabilities")
async def capabilities():
    return {"supported_file_types": ["pdf", "docx"], "implemented_file_types": ["pdf", "docx"],
            "engine": "mineru-pipeline,python-docx"}


@router.post("/v1/document-resources", response_model=ResourceResponse)
async def create_document_resource(files: list[UploadFile] = File(...)) -> ResourceResponse:
    try:
        if not files:
            raise ValueError("files must be non-empty")
        for file in files:
            processor.detect_file_type(file_type=None, filename=file.filename or "")
            await file.seek(0)
        proxies = [UploadFileProxy(file.filename or "", file.file) for file in files]
        return await run_in_threadpool(_prepare, proxies)
    except (processor.InvalidFileObjectError, processor.UnsupportedFileTypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"document resource preparation failed: {exc}") from exc


def _prepare(files: list[UploadFileProxy]) -> ResourceResponse:
    documents = []
    for file in files:
        try:
            result = processor.process(file)
        except Exception as exc:
            raise RuntimeError(f"document parsing failed for {file.filename}: {exc}") from exc
        documents.append(InputDocument(filename=result.filename, html=result.html))
    return ResourceResponse(resource_path=prepare_resources(documents), documents=documents)
