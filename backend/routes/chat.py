"""completion/resume/cancel → manager 命令；SSE 先发历史快照，再消费独立订阅。"""

import asyncio
import json

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse
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
    session_id: str | None = Field(default=None, min_length=1)
    request_id: str | None = Field(default=None, min_length=1, max_length=200)
    run_options: dict | None = None


class CancelInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1)
    turn_id: str = Field(min_length=1)


async def _input(request):
    files = []
    settings = request.app.state.settings
    if request.headers.get("content-type", "").startswith("multipart/form-data"):
        async with request.form(max_files=settings.upload_max_files, max_fields=8) as form:
            values = {}
            total = 0
            for key, value in form.multi_items():
                if isinstance(value, UploadFile):
                    if key not in {"file", "files"}:
                        raise ValidationError("未知的文件字段")
                    content = bytearray()
                    while chunk := await value.read(64 * 1024):
                        total += len(chunk)
                        if total > settings.upload_max_bytes:
                            raise HTTPException(status_code=413, detail="上传超过大小限制")
                        content.extend(chunk)
                    files.append({"filename": value.filename or "", "content": bytes(content)})
                else:
                    if key in values:
                        raise ValidationError("重复的表单字段")
                    values[key] = json.loads(value) if key == "run_options" else value
    else:
        values = await request.json()
    return CompletionInput.model_validate(values), files


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
                payload = {key: value for key, value in event.items() if key != "seq"}
                yield "event: session.event\ndata: " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n\n"
                if event["turn_id"] == target_turn and event["type"] in {"turn.completed", "turn.failed", "turn.cancelled"}:
                    return
        finally:
            await manager.detach(context.subscription.id)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
                             background=BackgroundTask(manager.detach, context.subscription.id))


@router.post("/chat/completion")
async def completion(request: Request):
    try:
        body, files = await _input(request)
        manager, context = await request.app.state.session_registry.complete(**body.model_dump(), files=files)
        return await _response(request, manager, context)
    except (PydanticValidationError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except BackendServiceError as exc:
        raise_http_error(exc)


@router.get("/resume")
async def resume(request: Request, session_id: str):
    try:
        manager = await request.app.state.session_registry.get_or_load(session_id)
        context = await manager.attach()
        return await _response(request, manager, context)
    except BackendServiceError as exc:
        raise_http_error(exc)


@router.post("/cancel")
async def cancel(request: Request, body: CancelInput):
    try:
        manager = await request.app.state.session_registry.get_or_load(body.session_id)
        row = await manager.cancel(body.turn_id)
        return {"session_id": body.session_id, "turn_id": body.turn_id, "status": row["status"]}
    except BackendServiceError as exc:
        raise_http_error(exc)
