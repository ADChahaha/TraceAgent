from __future__ import annotations

import json

from file_extraction_agent import extractor_client as extractor_client_module
from file_extraction_agent import processor as processor_module
from file_extraction_agent.schemas import (
    BroadTrace,
    ExtractionContent,
    ExtractionResult,
    ExtractionTrace,
    FieldDefinition,
    FieldTraceRecord,
    GraphInput,
    NormalizedBlock,
    ResolvedFieldResult,
    TaskSpec,
)


def _build_result(
    *,
    field_name: str = "invoice_no",
    status: str = "resolved",
    final_value: str | None = "INV-001",
    reason: str | None = "图编排已完成",
    failure_reason: str | None = None,
) -> ExtractionResult:
    return ExtractionResult(
        result=ExtractionContent(
            fields=[
                ResolvedFieldResult(
                    field_name=field_name,
                    status=status,  # type: ignore[arg-type]
                    final_value=final_value,
                )
            ]
        ),
        trace=ExtractionTrace(
            fields=[
                FieldTraceRecord(
                    field_name=field_name,
                    status=status,  # type: ignore[arg-type]
                    broad_trace=BroadTrace(local_status="evidence_found"),
                    used_field_outputs=[field_name] if status == "resolved" else [],
                    reason=reason,
                    failure_reason=failure_reason,
                )
            ]
        ),
    )


def test_extract_delegates_graph_input_building_to_input_adapter(monkeypatch):
    seen_call: dict[str, object] = {}
    seen_graph_call: dict[str, object] = {}
    expected_graph_input = GraphInput(
        blocks=[NormalizedBlock(document_id="doc-from-adapter", text="适配后内容")],
        task_spec=TaskSpec(
            task_name="invoice",
            fields=[
                FieldDefinition(
                    field_name="invoice_no",
                    display_name="发票号",
                    type="string",
                )
            ],
        ),
    )

    def fake_build_graph_input(**kwargs):
        seen_call.update(kwargs)
        return expected_graph_input

    fake_client = object()

    def fake_run_extraction_graph(*, graph_input, extractor_client):
        seen_graph_call["graph_input"] = graph_input
        seen_graph_call["extractor_client"] = extractor_client
        return _build_result(final_value="INV-ADAPTER")

    monkeypatch.setattr(processor_module, "build_graph_input", fake_build_graph_input)
    monkeypatch.setattr(
        processor_module,
        "run_extraction_graph",
        fake_run_extraction_graph,
        raising=False,
    )

    result = processor_module.extract(
        blocks=[NormalizedBlock(document_id="doc-raw", text="原始输入")],
        task_spec=TaskSpec(
            task_name="ignored",
            fields=[
                FieldDefinition(
                    field_name="ignored",
                    display_name="忽略字段",
                    type="string",
                )
            ],
        ),
        metadata={"source": "backend"},
        extractor_client=fake_client,
    )

    assert seen_call["blocks"][0].document_id == "doc-raw"
    assert seen_call["metadata"] == {"source": "backend"}
    assert seen_graph_call["graph_input"] == expected_graph_input
    assert seen_graph_call["extractor_client"] is fake_client
    assert result.result.fields[0].final_value == "INV-ADAPTER"


def test_extract_delegates_execution_to_graph_with_built_client():
    seen_graph_call: dict[str, object] = {}
    fake_client = object()

    def fake_run_extraction_graph(*, graph_input, extractor_client):
        seen_graph_call["graph_input"] = graph_input
        seen_graph_call["extractor_client"] = extractor_client
        return _build_result(final_value="INV-001")

    processor_module.run_extraction_graph = fake_run_extraction_graph

    result = processor_module.extract(
        blocks=[
            NormalizedBlock(
                document_id="doc-1",
                text="发票号码：INV-001",
                page_no=1,
            )
        ],
        task_spec=TaskSpec(
            task_name="invoice",
            fields=[
                FieldDefinition(
                    field_name="invoice_no",
                    display_name="发票号",
                    type="string",
                    required=True,
                )
            ],
        ),
        extractor_client=fake_client,
    )

    assert isinstance(result, ExtractionResult)
    assert seen_graph_call["extractor_client"] is fake_client
    assert seen_graph_call["graph_input"].blocks[0].document_id == "doc-1"
    assert result.result.fields[0].status == "resolved"
    assert result.result.fields[0].final_value == "INV-001"
    assert result.trace.fields[0].used_field_outputs == ["invoice_no"]


def test_extract_passes_structured_output_strategy_to_client_builder(monkeypatch):
    seen_builder_call: dict[str, object] = {}
    fake_client = object()

    def fake_builder(*, base_url, api_key, model, structured_output_strategy):
        seen_builder_call["base_url"] = base_url
        seen_builder_call["api_key"] = api_key
        seen_builder_call["model"] = model
        seen_builder_call["structured_output_strategy"] = structured_output_strategy
        return fake_client

    def fake_run_extraction_graph(*, graph_input, extractor_client):
        assert graph_input.blocks[0].document_id == "doc-1"
        assert extractor_client is fake_client
        return ExtractionResult(
            result=ExtractionContent(fields=[]),
            trace=ExtractionTrace(fields=[]),
        )

    monkeypatch.setattr(
        processor_module,
        "build_extractor_client",
        fake_builder,
    )
    monkeypatch.setattr(
        processor_module,
        "run_extraction_graph",
        fake_run_extraction_graph,
        raising=False,
    )

    processor_module.extract(
        blocks=[NormalizedBlock(document_id="doc-1", text="内容")],
        task_spec=TaskSpec(
            task_name="invoice",
            fields=[
                FieldDefinition(
                    field_name="invoice_no",
                    display_name="发票号",
                    type="string",
                )
            ],
        ),
        base_url="https://llm.example.com/v1",
        openai_api_key="test-key",
        model="gpt-compatible",
        structured_output_strategy="json_schema",
    )

    assert seen_builder_call["base_url"] == "https://llm.example.com/v1"
    assert seen_builder_call["api_key"] == "test-key"
    assert seen_builder_call["model"] == "gpt-compatible"
    assert seen_builder_call["structured_output_strategy"] == "json_schema"


def test_extract_requires_explicit_connection_params_when_client_is_not_provided():
    try:
        processor_module.extract(
            blocks=[NormalizedBlock(document_id="doc-1", text="内容")],
            task_spec=TaskSpec(
                task_name="invoice",
                fields=[
                    FieldDefinition(
                        field_name="invoice_no",
                        display_name="发票号",
                        type="string",
                    )
                ],
            ),
        )
    except extractor_client_module.ExtractorClientConfigError as exc:
        message = str(exc)
        assert "base_url" in message
        assert "api_key" in message
        assert "model" in message
    else:
        raise AssertionError("未传 extractor_client 时应要求显式连接参数")


def test_extract_loads_task_spec_from_task_spec_name(monkeypatch, tmp_path):
    task_spec_dir = tmp_path / "task_specs"
    task_spec_dir.mkdir()
    (task_spec_dir / "invoice.json").write_text(
        json.dumps(
            {
                "task_name": "invoice",
                "fields": [
                    {
                        "field_name": "invoice_no",
                        "display_name": "发票号",
                        "type": "string",
                        "required": True,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(processor_module, "TASK_SPECS_DIR", task_spec_dir)

    def fake_run_extraction_graph(*, graph_input, extractor_client):
        del extractor_client
        assert graph_input.task_spec.task_name == "invoice"
        return _build_result(
            status="failed",
            final_value=None,
            reason=None,
            failure_reason="未找到可用证据",
        )

    monkeypatch.setattr(
        processor_module,
        "run_extraction_graph",
        fake_run_extraction_graph,
        raising=False,
    )

    result = processor_module.extract(
        blocks=[NormalizedBlock(document_id="doc-2", text="空白")],
        task_spec_name="invoice",
        extractor_client=object(),
    )

    assert result.result.fields[0].field_name == "invoice_no"
    assert result.result.fields[0].status == "failed"
    assert result.trace.fields[0].failure_reason == "未找到可用证据"


def test_extract_returns_graph_result_without_reimplementing_field_fill():
    def fake_run_extraction_graph(*, graph_input, extractor_client):
        del graph_input, extractor_client
        return ExtractionResult(
            result=ExtractionContent(
                fields=[
                    ResolvedFieldResult(
                        field_name="invoice_no",
                        status="resolved",
                        final_value="INV-003",
                    ),
                    ResolvedFieldResult(field_name="amount", status="failed"),
                ]
            ),
            trace=ExtractionTrace(
                fields=[
                    FieldTraceRecord(
                        field_name="invoice_no",
                        status="resolved",
                        broad_trace=BroadTrace(local_status="evidence_found"),
                        used_field_outputs=["invoice_no"],
                        reason="图编排已完成",
                    ),
                    FieldTraceRecord(
                        field_name="amount",
                        status="failed",
                        broad_trace=BroadTrace(local_status="missing"),
                        failure_reason="未找到可用证据",
                    ),
                ]
            ),
        )

    processor_module.run_extraction_graph = fake_run_extraction_graph

    result = processor_module.extract(
        blocks=[NormalizedBlock(document_id="doc-3", text="只命中一个字段")],
        task_spec=TaskSpec(
            task_name="invoice",
            fields=[
                FieldDefinition(field_name="invoice_no", display_name="发票号", type="string"),
                FieldDefinition(field_name="amount", display_name="金额", type="money"),
            ],
        ),
        extractor_client=object(),
    )

    assert [field.field_name for field in result.result.fields] == [
        "invoice_no",
        "amount",
    ]
    assert result.result.fields[0].status == "resolved"
    assert result.result.fields[1].status == "failed"


def test_extract_rejects_missing_task_spec_and_task_spec_name():
    try:
        processor_module.extract(
            blocks=[NormalizedBlock(document_id="doc-4", text="")],
        )
    except ValueError as exc:
        assert "task_spec" in str(exc)
    else:
        raise AssertionError("缺少 task_spec 和 task_spec_name 时应拒绝继续执行")
