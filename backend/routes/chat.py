"""completion/resume/cancel → manager 命令；会话与文件独立成 API；SSE 先发历史快照，再消费独立订阅。"""

import asyncio
import json
from urllib.parse import quote

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError as PydanticValidationError
from starlette.background import BackgroundTask
from starlette.datastructures import UploadFile

from backend.routes.errors import raise_http_error
from backend.services.errors import BackendServiceError, ValidationError
from backend.services.session_history import build_snapshot
from backend.services.subscription import SubscriptionClosed


router = APIRouter(tags=["chat"])


class CompletionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    run_options: dict | None = None


class CancelInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1)
    turn_id: str = Field(min_length=1)


async def _read_files(request):
    """multipart -> [{"filename", "content"}]；文件字段、分块读取和大小限制在这里统一处理。"""
    settings = request.app.state.settings
    if not request.headers.get("content-type", "").startswith("multipart/form-data"):
        raise HTTPException(status_code=422, detail="上传必须使用 multipart/form-data")
    files = []
    async with request.form(max_files=settings.upload_max_files, max_fields=8) as form:
        for key, value in form.multi_items():
            if not isinstance(value, UploadFile):
                raise HTTPException(status_code=422, detail="未知的表单字段")
            if key not in {"file", "files"}:
                raise ValidationError("未知的文件字段")
            content = bytearray()
            while chunk := await value.read(64 * 1024):
                content.extend(chunk)
            files.append({"filename": value.filename or "", "content": bytes(content)})
    total = sum(len(file["content"]) for file in files)
    if total > settings.upload_max_bytes:
        raise HTTPException(status_code=413, detail="上传超过大小限制")
    return files


async def _response(request, manager, context):
    try:
        snapshot = await asyncio.wait_for(build_snapshot(request.app.state.database, context), 30)
        if context.subscription.closed.is_set():
            raise BackendServiceError("恢复期间订阅溢出，请重新连接")
        target_turn = snapshot["state"]["active_turn_id"]
        first = "event: session.snapshot\ndata: " + json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")) + "\n\n"
        # 首帧已编码，不让长连接额外保留历史对象与当前轮副本。
        del snapshot
        context.current_turn = None
    except BaseException:
        await manager.detach(context.subscription.id)
        raise

    async def stream():
        nonlocal first
        try:
            yield first
            first = None
            if target_turn is None:
                return
            while True:
                try:
                    event = await asyncio.wait_for(context.subscription.receive(), request.app.state.settings.sse_heartbeat_seconds)
                except TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                except SubscriptionClosed:
                    return
                yield "event: session.event\ndata: " + json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n\n"
                if event["turn_id"] == target_turn and event["type"] in {"turn.completed", "turn.failed", "turn.cancelled"}:
                    return
        finally:
            await manager.detach(context.subscription.id)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
                             background=BackgroundTask(manager.detach, context.subscription.id))


@router.post("/chat/sessions")
async def create_session(request: Request):
    try:
        session_id = await request.app.state.session_registry.create_session()
        return {"session_id": session_id}
    except BackendServiceError as exc:
        raise_http_error(exc)


@router.post("/chat/sessions/{session_id}/files")
async def upload_files(request: Request, session_id: str):
    try:
        files = await _read_files(request)
        manager = await request.app.state.session_registry.get_or_create(session_id)
        resources = await manager.upload_files(files=files)
        return {"resources": resources}
    except BackendServiceError as exc:
        raise_http_error(exc)


@router.delete("/chat/sessions/{session_id}/files/{resource_id}")
async def remove_file(request: Request, session_id: str, resource_id: str):
    try:
        manager = await request.app.state.session_registry.get_or_create(session_id)
        resources = await manager.remove_file(resource_id=resource_id)
        return {"resource_id": resource_id, "resources": resources}
    except BackendServiceError as exc:
        raise_http_error(exc)


@router.get("/chat/sessions/{session_id}/blocks")
async def read_block(request: Request, session_id: str, key: str):
    """按引用 key 返回段落原文，供前端回溯引用；key 归属由会话桶隔离。"""
    try:
        manager = await request.app.state.session_registry.get_or_create(session_id)
        return await manager.read_block(key)
    except BackendServiceError as exc:
        raise_http_error(exc)


@router.get("/chat/sessions/{session_id}/files/{resource_id}")
async def download_file(request: Request, session_id: str, resource_id: str):
    """下载会话里的原始文件字节；资源归属由会话隔离。"""
    try:
        manager = await request.app.state.session_registry.get_or_create(session_id)
        resource, data = await manager.download_file(resource_id=resource_id)
    except BackendServiceError as exc:
        raise_http_error(exc)
    filename = resource["location"].rsplit("/", 1)[-1]
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.get("/chat/sessions/{session_id}/documents")
async def list_documents(request: Request, session_id: str):
    """列出会话归档内的处理后 md 文件（key 与大小），供前端浏览文档树。"""
    try:
        manager = await request.app.state.session_registry.get_or_create(session_id)
        return {"documents": await manager.list_documents()}
    except BackendServiceError as exc:
        raise_http_error(exc)


@router.get("/chat/sessions/{session_id}/documents/content")
async def read_document(request: Request, session_id: str, key: str):
    """按归档 key 返回处理后 md 文件全文，供前端查看文档。"""
    try:
        manager = await request.app.state.session_registry.get_or_create(session_id)
        return await manager.read_document(key)
    except BackendServiceError as exc:
        raise_http_error(exc)


@router.post("/chat/completion")
async def completion(request: Request):
    try:
        body = CompletionInput.model_validate(await request.json())
        manager = await request.app.state.session_registry.get_or_create(body.session_id)
        context = await manager.create_completion(content=body.content, run_options=body.run_options)
        return await _response(request, manager, context)
    except (PydanticValidationError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except BackendServiceError as exc:
        raise_http_error(exc)


@router.get("/resume")
async def resume(request: Request, session_id: str):
    try:
        manager = await request.app.state.session_registry.get_or_create(session_id)
        context = await manager.attach()
        return await _response(request, manager, context)
    except BackendServiceError as exc:
        raise_http_error(exc)


@router.post("/cancel")
async def cancel(request: Request, body: CancelInput):
    try:
        manager = await request.app.state.session_registry.get(body.session_id)
        row = await manager.cancel(body.turn_id)
        return {"session_id": body.session_id, "turn_id": body.turn_id, "status": row["status"]}
    except BackendServiceError as exc:
        raise_http_error(exc)
