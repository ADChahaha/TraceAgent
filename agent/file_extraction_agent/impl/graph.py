"""file_extraction_agent 的内部 graph 编排层。

实现步骤：

```text
调用方传入已经组装好的 GraphInput 和 extractor_client
  -> run_extraction_graph(...) 先调用 build_graph_state(graph_input) 创建空执行态
  -> run_broad_extraction(state, extractor_client) 写入第一阶段 broad_output
  -> run_resolution(state) 基于 broad_output 写入 resolved_fields
  -> 从最终 state 读取 broad_output / resolved_fields / warnings
  -> 汇总成 ExtractionResult 返回给 processor 或其他上层调用方
```
"""

from __future__ import annotations

from typing import Any

from file_extraction_agent.impl.broad_extraction import run_broad_extraction
from file_extraction_agent.impl.resolution import run_resolution
from file_extraction_agent.impl.state import build_graph_state
from file_extraction_agent.schemas import ExtractionResult, GraphInput, RunTrace


def run_extraction_graph(
    *,
    graph_input: GraphInput,
    extractor_client: Any,
) -> ExtractionResult:
    """串联 broad extraction 与 resolution 两个内部节点。"""

    state = build_graph_state(graph_input)
    state = run_broad_extraction(state=state, extractor_client=extractor_client)
    state = run_resolution(state=state)

    if state.broad_output is None:
        raise ValueError("graph finished without broad_output")

    return ExtractionResult(
        broad_output=state.broad_output,
        resolved_fields=state.resolved_fields,
        run_trace=RunTrace(
            rounds=1,
            warnings=state.warnings,
        ),
    )
