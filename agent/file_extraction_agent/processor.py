"""file_extraction_agent 对外统一入口。"""

from __future__ import annotations

from typing import Any, Literal

from file_extraction_agent import input_adapter
from file_extraction_agent.extractor_client import build_extractor_client
from file_extraction_agent.impl.graph import run_extraction_graph
from file_extraction_agent.impl.schemas import RunOptions
from file_extraction_agent.input_adapter import build_graph_input
from file_extraction_agent.schemas import (
    ExtractionResult,
    NormalizedBlock,
    TaskSpec,
)


TASK_SPECS_DIR = input_adapter.TASK_SPECS_DIR
TaskSpecNotFoundError = input_adapter.TaskSpecNotFoundError
StructuredOutputStrategy = Literal["json_schema", "tool_call", "auto"]


def extract(
    *,
    blocks: list[NormalizedBlock],
    markdown: str = "",
    md_list: list[str] | None = None,
    task_spec: TaskSpec | None = None,
    task_spec_name: str | None = None,
    run_options: RunOptions | None = None,
    metadata: dict[str, Any] | None = None,
    base_url: str | None = None,
    openai_api_key: str | None = None,
    model: str | None = None,
    structured_output_strategy: StructuredOutputStrategy = "auto",
    extractor_client: Any | None = None,
) -> ExtractionResult:
    """消费外部已校验好的输入，执行最小可用的字段抽取收口流程。"""

    input_adapter.TASK_SPECS_DIR = TASK_SPECS_DIR
    extraction_input = build_graph_input(
        blocks=blocks,
        markdown=markdown,
        md_list=md_list,
        task_spec=task_spec,
        task_spec_name=task_spec_name,
        run_options=run_options,
        metadata=metadata,
    )
    client = (
        extractor_client
        if extractor_client is not None
        else build_extractor_client(
            base_url=base_url,
            api_key=openai_api_key,
            model=model,
            structured_output_strategy=structured_output_strategy,
        )
    )
    return run_extraction_graph(
        extraction_input=extraction_input,
        extractor_client=client,
    )
