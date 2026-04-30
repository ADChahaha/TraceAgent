"""file_extraction_agent 对外统一入口。"""

from __future__ import annotations

from typing import Any, Literal

from service.file_extraction_agent.extractor_client import build_extractor_client
from service.file_extraction_agent.impl.graph import run_extraction_graph
from service.file_extraction_agent.input_adapter import build_graph_input
from service.file_extraction_agent.schemas import (
    ExtractionResult,
    NormalizedBlock,
    RunOptions,
    TaskSpec,
)


StructuredOutputStrategy = Literal["tool_call"]


def extract(
    *,
    blocks: list[NormalizedBlock],
    markdown: str = "",
    md_list: list[str] | None = None,
    task_spec: TaskSpec | None = None,
    run_options: RunOptions | dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    base_url: str | None = None,
    openai_api_key: str | None = None,
    model: str | None = None,
    broad_model: str | None = None,
    resolution_model: str | None = None,
    structured_output_strategy: StructuredOutputStrategy = "tool_call",
    extractor_client: Any | None = None,
    broad_extractor_client: Any | None = None,
    resolution_extractor_client: Any | None = None,
) -> ExtractionResult:
    """消费外部已校验好的输入，执行最小可用的字段抽取收口流程。"""

    extraction_input = build_graph_input(
        blocks=blocks,
        markdown=markdown,
        md_list=md_list,
        task_spec=task_spec,
        run_options=run_options,
        metadata=metadata,
    )
    client = extractor_client
    if _needs_shared_client(
        extractor_client=client,
        broad_extractor_client=broad_extractor_client,
        resolution_extractor_client=resolution_extractor_client,
        broad_model=broad_model,
        resolution_model=resolution_model,
    ):
        client = build_extractor_client(
            base_url=base_url,
            api_key=openai_api_key,
            model=model,
            structured_output_strategy=structured_output_strategy,
        )

    if broad_extractor_client is None and broad_model is not None:
        broad_extractor_client = build_extractor_client(
            base_url=base_url,
            api_key=openai_api_key,
            model=broad_model,
            structured_output_strategy=structured_output_strategy,
        )
    if resolution_extractor_client is None and resolution_model is not None:
        resolution_extractor_client = build_extractor_client(
            base_url=base_url,
            api_key=openai_api_key,
            model=resolution_model,
            structured_output_strategy=structured_output_strategy,
        )

    if broad_extractor_client is None and resolution_extractor_client is None:
        return run_extraction_graph(
            extraction_input=extraction_input,
            extractor_client=client,
        )
    return run_extraction_graph(
        extraction_input=extraction_input,
        extractor_client=client,
        broad_extractor_client=broad_extractor_client,
        resolution_extractor_client=resolution_extractor_client,
    )


def _needs_shared_client(
    *,
    extractor_client: Any | None,
    broad_extractor_client: Any | None,
    resolution_extractor_client: Any | None,
    broad_model: str | None,
    resolution_model: str | None,
) -> bool:
    if extractor_client is not None:
        return False
    broad_has_client = broad_extractor_client is not None or broad_model is not None
    resolution_has_client = (
        resolution_extractor_client is not None or resolution_model is not None
    )
    return not broad_has_client or not resolution_has_client
