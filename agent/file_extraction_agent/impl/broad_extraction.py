"""file_extraction_agent 的 broad extraction 节点。

实现步骤：

```text
GraphState(graph_input=..., broad_output=None)
  -> run_broad_extraction(...) 读取 state.graph_input
  -> build_broad_extraction_messages(graph_input) 生成 BroadExtractionOutput prompt
  -> extractor_client.invoke(output_schema=BroadExtractionOutput, messages=...)
  -> 将客户端返回的 BroadExtractionOutput 写入 state.broad_output
  -> 返回同一个 GraphState，交给后续 validation / resolution 节点继续处理
```
"""

from __future__ import annotations

from typing import Any

from file_extraction_agent.impl.prompts import build_broad_extraction_messages
from file_extraction_agent.impl.state import GraphState
from file_extraction_agent.schemas import BroadExtractionOutput


def run_broad_extraction(
    *,
    state: GraphState,
    extractor_client: Any,
) -> GraphState:
    """执行第一阶段字段候选抽取，并把结果写回图状态。"""

    broad_output = extractor_client.invoke(
        output_schema=BroadExtractionOutput,
        messages=build_broad_extraction_messages(state.graph_input),
    )
    state.broad_output = broad_output
    return state
