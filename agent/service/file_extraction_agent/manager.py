"""问答注册表：校验输入与资源 → 装配模型 → 注册 CompletionRuntime → 流结束后移除。

CompletionManager 根据 completion_id 查找、取消或查询运行时；SSE、线程、队列和
单轮终态由 completion_runtime.py 负责。注册表仅在单进程中有效，问答结束保留资源。
"""

from __future__ import annotations

import re
import threading
from typing import Any, Iterable

from service.file_extraction_agent.completion_runtime import CompletionRuntime
from service.file_extraction_agent.core.model import build_qa_model
from service.file_extraction_agent.core.tools.workspace import validate_resource
from service.file_extraction_agent.schemas import DocumentQaMessage, ModelConfig, RunOptions


class CompletionManager:
    """进程内多个 document-QA chat completion 的注册表与协调。

    create(...) 装配 路径 + model，构造一个 CompletionRuntime（单 completion 的
    运行时）并注册，返回其 stream() 产出的 SSE 流；terminate / get_status 转发到
    对应 runtime；stream 结束后由托管包装从注册表移除。单实例持有注册表 + 锁，
    应按单进程单实例部署（多 uvicorn worker 不同进程间不共享 cancel 状态）。
    """

    def __init__(self) -> None:
        self._completions: dict[str, CompletionRuntime] = {}
        self._lock = threading.Lock()

    def create(
        self,
        *,
        completion_id: str,
        resource_path: str,
        messages: list[DocumentQaMessage],
        model_config: ModelConfig | None = None,
        run_options: RunOptions | None = None,
    ) -> Iterable[str]:
        if not isinstance(completion_id, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", completion_id) is None:
            raise ValueError("completion_id must be a safe non-empty identifier")
        if not messages:
            raise ValueError("messages must be a non-empty list")
        validate_resource(resource_path)
        qa_model = build_qa_model(model_config)
        runtime = CompletionRuntime(resource_path, qa_model, messages, run_options)
        with self._lock:
            if completion_id in self._completions:
                raise ValueError("completion_id is already active")
            self._completions[completion_id] = runtime
        return self._managed_stream(completion_id, runtime)

    def terminate(self, completion_id: str) -> dict[str, Any]:
        with self._lock:
            runtime = self._completions.get(completion_id)
        if runtime is None:
            return {"id": completion_id, "status": "not_found"}
        status = runtime.terminate()
        return {"id": completion_id, "status": status}

    def get_status(self, completion_id: str) -> dict[str, Any] | None:
        with self._lock:
            runtime = self._completions.get(completion_id)
        if runtime is None:
            return None
        return {"id": completion_id, "status": runtime.get_status()}

    def _managed_stream(self, completion_id: str, runtime: CompletionRuntime) -> Iterable[str]:
        """闭包绑定 ID 与运行时，流结束只移除仍指向该对象的注册项。"""
        def run() -> Iterable[str]:
            try:
                yield from runtime.stream()
            finally:
                with self._lock:
                    if self._completions.get(completion_id) is runtime:
                        self._completions.pop(completion_id, None)

        return run()


completion_manager = CompletionManager()


__all__ = ["CompletionManager", "completion_manager"]
