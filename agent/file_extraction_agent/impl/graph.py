"""file_extraction_agent 的内部 graph 编排层。

实现步骤：

```text
GraphInput + extractor_client
  -> build_graph_state(graph_input)
  -> run_broad_extraction(state, extractor_client)
  -> run_resolution(state)
  -> ExtractionResult(result + trace)
```
"""

from __future__ import annotations

from typing import Any

from file_extraction_agent.impl.broad_extraction import run_broad_extraction
from file_extraction_agent.impl.resolution import run_resolution
from file_extraction_agent.impl.state import build_graph_state
from file_extraction_agent.schemas import (
    ExtractionContent,
    ExtractionResult,
    ExtractionTrace,
    GraphInput,
)


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
        result=ExtractionContent(fields=state.result_fields),
        trace=ExtractionTrace(
            fields=state.trace_fields,
            warnings=state.warnings,
        ),
    )
