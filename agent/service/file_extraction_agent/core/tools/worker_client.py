"""父进程侧工具子进程客户端：组请求 → 启动统一 worker → 解析响应 → finally kill。

实现步骤：

```text
run_operation(operation, args, workspace)
  -> 组装 JSON 请求（workspace 可选全量传入）
  -> asyncio.create_subprocess_exec(python -m ...tools.worker)
  -> stdin 写请求，等待 stdout 响应（受 WORKER_TIMEOUT_SECONDS 限制）
  -> 非 0 退出且无 stdout、响应非法 JSON、非对象都转统一错误结果
  -> finally kill 子进程；取消/超时/失败都不留残留

prepare_workspace(resource_refs)
  -> resource_refs 为空直接抛 ValueError（不启动子进程）
  -> run_operation(operation="prepare", args={resource_path: [...]})
  -> worker 返回 workspace payload 时返回它
  -> kind=invalid 抛 ValueError；其余失败抛 RuntimeError
```
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from service.file_extraction_agent.schemas import ResourceRefs

WORKER_MODULE = "service.file_extraction_agent.core.tools.worker"
WORKER_TIMEOUT_SECONDS = 120.0
AGENT_ROOT = Path(__file__).resolve().parents[4]


def _worker_command() -> list[str]:
    return [sys.executable, "-m", WORKER_MODULE]


def _kill(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass


async def run_operation(
    *,
    operation: str,
    args: dict[str, Any],
    workspace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """启动一个工具子进程执行 operation；无论结果如何都在 finally kill。"""
    request: dict[str, Any] = {"operation": operation, "args": args}
    if workspace is not None:
        request["workspace"] = workspace
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(AGENT_ROOT), env.get("PYTHONPATH", "")) if part
    )
    process = await asyncio.create_subprocess_exec(
        *_worker_command(),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(AGENT_ROOT),
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(json.dumps(request, ensure_ascii=False).encode("utf-8")),
            timeout=WORKER_TIMEOUT_SECONDS,
        )
        if process.returncode != 0 and not stdout:
            return _error(f"tool worker failed: {stderr.decode('utf-8', 'replace')[:500]}")
        try:
            response = json.loads(stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return _error(f"invalid tool worker response: {exc}")
        if not isinstance(response, dict):
            return _error("invalid tool worker response")
        return response
    except asyncio.TimeoutError:
        return _error("tool worker timed out")
    finally:
        _kill(process)


async def prepare_workspace(resource_refs: ResourceRefs) -> dict[str, Any]:
    """资源定位数组 → prepare 子进程 → workspace payload；失败映射 ValueError/RuntimeError。"""
    refs = [_ref_to_dict(ref) for ref in resource_refs]
    if not refs:
        raise ValueError("resource_path is required")
    response = await run_operation(operation="prepare", args={"resource_path": refs})
    if response.get("ok") is True and isinstance(response.get("workspace"), dict):
        return response["workspace"]
    message = str(response.get("message") or _first_error_message(response) or "workspace preparation failed")
    if response.get("kind") == "invalid":
        raise ValueError(message)
    raise RuntimeError(message)


def _ref_to_dict(ref: Any) -> dict[str, Any]:
    if isinstance(ref, dict):
        return {"type": ref.get("type"), "location": ref.get("location")}
    return {"type": getattr(ref, "type"), "location": getattr(ref, "location")}


def _error(message: str) -> dict[str, Any]:
    """进程级失败同时给出工具错误结构和 prepare 映射字段。"""
    return {
        "ok": False,
        "errors": [{"message": message}],
        "kind": "internal",
        "message": message,
    }


def _first_error_message(response: dict[str, Any]) -> str | None:
    errors = response.get("errors")
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        return str(errors[0].get("message") or "") or None
    return None


__all__ = ["prepare_workspace", "run_operation"]
