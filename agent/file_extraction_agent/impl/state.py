"""file_extraction_agent 图内部执行态。

实现步骤：

```text
graph.py 或其他内部节点拿到已经组装好的 GraphInput
  -> 调用 build_graph_state(graph_input)
  -> 生成 GraphState(graph_input=..., broad_output=None, resolved_fields=[], warnings=[])
  -> broad_extraction.py 后续把 broad_output 写回状态
  -> resolution.py 基于 broad_output 一次性写回 resolved_fields
  -> 最终所有节点共享同一个中间态对象完成流程接力
```
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from file_extraction_agent.schemas import (
    BroadExtractionOutput,
    GraphInput,
    ResolvedFieldOutput,
)


class GraphState(BaseModel):
    """图运行过程中的共享状态容器。"""

    graph_input: GraphInput
    broad_output: BroadExtractionOutput | None = None
    resolved_fields: list[ResolvedFieldOutput] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def build_graph_state(graph_input: GraphInput) -> GraphState:
    """基于入口 GraphInput 创建一份空的执行态。"""

    return GraphState(graph_input=graph_input)
