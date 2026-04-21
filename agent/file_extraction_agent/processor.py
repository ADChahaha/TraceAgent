"""file_extraction_agent 对外统一入口。

实现步骤：

```text
调用方传入 session_id + documents，再传 task_spec 或 task_spec_name
  -> extract(...) 先把外部 session 输入交给 input_adapter.build_graph_input(...)
  -> input_adapter 负责选择 task_spec：显式传入就直接用；否则按 task_spec_name 从 task_specs/*.json 加载
  -> input_adapter 再用 session_id / documents / task_spec / run_config / metadata 组装 GraphInput
  -> 如果没传 extractor_client，就调用 build_extractor_client_from_env() 构造默认客户端
  -> 把 GraphInput 和 ExtractorClient 交给 impl/graph.py
  -> graph 依次驱动 broad extraction 和 resolution
  -> 返回 graph 汇总后的 ExtractionResult
```
"""

from __future__ import annotations

from typing import Any

from file_extraction_agent.extractor_client import build_extractor_client_from_env
from file_extraction_agent import input_adapter
from file_extraction_agent.impl.graph import run_extraction_graph
from file_extraction_agent.input_adapter import build_graph_input
from file_extraction_agent.schemas import (
    ExtractionResult,
    NormalizedDocument,
    RunConfig,
    TaskSpec,
)


TASK_SPECS_DIR = input_adapter.TASK_SPECS_DIR
TaskSpecNotFoundError = input_adapter.TaskSpecNotFoundError


def extract(
    *,
    session_id: str,
    documents: list[NormalizedDocument],
    task_spec: TaskSpec | None = None,
    task_spec_name: str | None = None,
    run_config: RunConfig | None = None,
    metadata: dict[str, Any] | None = None,
    extractor_client: Any | None = None,
) -> ExtractionResult:
    """消费外部已校验好的输入，执行最小可用的字段抽取收口流程。"""

    input_adapter.TASK_SPECS_DIR = TASK_SPECS_DIR
    graph_input = build_graph_input(
        session_id=session_id,
        documents=documents,
        task_spec=task_spec,
        task_spec_name=task_spec_name,
        run_config=run_config,
        metadata=metadata,
    )
    client = (
        extractor_client
        if extractor_client is not None
        else build_extractor_client_from_env()
    )
    return run_extraction_graph(
        graph_input=graph_input,
        extractor_client=client,
    )
