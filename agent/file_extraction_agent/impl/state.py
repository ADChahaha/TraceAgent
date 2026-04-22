"""file_extraction_agent 图内部执行态。

实现步骤：

```text
GraphInput
  -> build_graph_state(graph_input)
  -> GraphState(graph_input=..., broad_output=None, result_fields=[], trace_fields=[])
  -> broad_extraction.py 写回 broad_output
  -> resolution.py 写回 result_fields 与 trace_fields
  -> graph.py 汇总成 ExtractionResult(result + trace)
```
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from file_extraction_agent.schemas import (
    BroadExtractionOutput,
    FieldTraceRecord,
    GraphInput,
    ResolvedFieldResult,
)


class GraphState(BaseModel):
    """图运行过程中的共享状态容器。"""

    graph_input: GraphInput
    broad_output: BroadExtractionOutput | None = None
    result_fields: list[ResolvedFieldResult] = Field(default_factory=list)
    trace_fields: list[FieldTraceRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def build_graph_state(graph_input: GraphInput) -> GraphState:
    """基于入口 GraphInput 创建一份空的执行态。"""

    return GraphState(graph_input=graph_input)
