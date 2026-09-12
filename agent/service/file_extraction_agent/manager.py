"""问答注册表：校验输入 → 装配模型 → 注册 CompletionRuntime → 流结束后移除。

CompletionManager 根据 completion_id 查找、取消或查询运行时；单轮的执行、事件流与终态
由 completion_runtime.py 负责，运行时通过注入的 on_close 回调在流结束时移除注册项。
资源预检与 workspace 准备由路由层在调用前交给 prepare 子进程完成，manager 只接收
已准备好的 workspace payload。注册表仅在单进程中有效，问答结束保留资源。
"""

from __future__ import annotations

import re
import threading
from typing import Any

from service.file_extraction_agent.completion_runtime import CompletionRuntime
from service.file_extraction_agent.core.model import build_qa_model
from service.file_extraction_agent.schemas import DocumentQaMessage, ModelConfig, RunOptions


class CompletionManager:
    """进程内多个 document-QA chat completion 的注册表与协调。

    create(...) 接收已完成预检的 workspace payload 并装配模型，构造一个 CompletionRuntime
    （单 completion 的运行时），注入结束时移除注册项的闭包并注册，返回该运行时；其
    stream() 产出事件字典流。terminate 取消对应 runtime，get_status 根据取消标志派生结果；
    收尾时通过 on_close 从注册表移除。单实例持有注册表 + 锁，应按单进程单实例部署；
    同进程协程与工作线程共享注册表，多进程不共享 cancel 状态。
    """

    def __init__(self) -> None:
        self._completions: dict[str, CompletionRuntime] = {}
        self._lock = threading.Lock()

    def create(
        self,
        *,
        completion_id: str,
        workspace: dict[str, Any],
        messages: list[DocumentQaMessage],
        model_config: ModelConfig | None = None,
        run_options: RunOptions | None = None,
    ) -> CompletionRuntime:
        if not isinstance(completion_id, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", completion_id) is None:
            raise ValueError("completion_id must be a safe non-empty identifier")
        if not messages:
            raise ValueError("messages must be a non-empty list")
        if not workspace:
            raise ValueError("workspace is required")
        qa_model = build_qa_model(model_config)
        runtime = CompletionRuntime(workspace, qa_model, messages, run_options)

        def remove() -> None:
            """闭包绑定 ID 与运行时，流结束只移除仍指向该对象的注册项。"""
            with self._lock:
                if self._completions.get(completion_id) is runtime:
                    self._completions.pop(completion_id, None)

        runtime._on_close = remove
        with self._lock:
            if completion_id in self._completions:
                raise ValueError("completion_id is already active")
            self._completions[completion_id] = runtime
        return runtime

    def terminate(self, completion_id: str) -> dict[str, Any]:
        with self._lock:
            runtime = self._completions.get(completion_id)
        if runtime is None:
            return {"id": completion_id, "status": "not_found"}
        runtime.terminate()
        return {"id": completion_id, "status": "cancelling"}

    def get_status(self, completion_id: str) -> dict[str, Any] | None:
        with self._lock:
            runtime = self._completions.get(completion_id)
        if runtime is None:
            return None
        return {"id": completion_id, "status": "cancelling" if runtime.cancel_requested else "in_progress"}


completion_manager = CompletionManager()


__all__ = ["CompletionManager", "completion_manager"]
