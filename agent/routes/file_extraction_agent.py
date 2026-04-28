"""把字段抽取业务结果适配成 HTTP 出口。

实现步骤：

```text
HTTP 调用方提交 blocks、markdown、显式 task_spec、run_options 和 metadata
  -> FastAPI 先用 service.file_extraction_agent.schemas 里的稳定输入对象解析请求体
  -> route 层不重新定义抽取业务结构，只把 HTTP JSON 转成 processor.extract(...) 的参数
  -> processor.extract(...) 负责输入适配、模型客户端构造和 graph 执行
  -> route 层把 ExtractionResult 作为响应返回
  -> 如果输入缺少 task spec 或模型连接参数不完整，就转换成 HTTP 422
```
"""

from __future__ import annotations

from importlib import import_module
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from service.file_extraction_agent.extractor_client import ExtractorClientConfigError
from service.file_extraction_agent.schemas import (
    ExtractionResult,
    NormalizedBlock,
    RunOptions,
    TaskSpec,
)


StructuredOutputStrategy = Literal["json_schema", "tool_call", "auto"]

router = APIRouter(tags=["file-extraction-agent"])


class ExtractRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    blocks: list[NormalizedBlock]
    markdown: str = ""
    md_list: list[str] = Field(default_factory=list)
    task_spec: TaskSpec | None = None
    run_options: RunOptions | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    base_url: str | None = None
    openai_api_key: str | None = None
    model: str | None = None
    structured_output_strategy: StructuredOutputStrategy = "auto"


@router.post("/v1/file-extraction-agent/extract", response_model=ExtractionResult)
async def extract_fields(request: ExtractRequest) -> ExtractionResult:
    try:
        return await run_in_threadpool(_extract_fields, request)
    except (ValueError, ExtractorClientConfigError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


def _extract_fields(request: ExtractRequest) -> ExtractionResult:
    extract = import_module("service.file_extraction_agent.processor").extract
    return extract(
        blocks=request.blocks,
        markdown=request.markdown,
        md_list=request.md_list,
        task_spec=request.task_spec,
        run_options=request.run_options,
        metadata=request.metadata,
        base_url=request.base_url,
        openai_api_key=request.openai_api_key,
        model=request.model,
        structured_output_strategy=request.structured_output_strategy,
    )
