from __future__ import annotations

import json

from file_extraction_agent import processor as processor_module
from file_extraction_agent.schemas import GraphInput
from file_extraction_agent.schemas import (
    BroadExtractionFieldOutput,
    BroadExtractionOutput,
    ExtractionResult,
    FieldDefinition,
    NormalizedBlock,
    NormalizedDocument,
    ResolvedFieldOutput,
    RunTrace,
    TaskSpec,
)


def test_extract_delegates_graph_input_building_to_input_adapter(monkeypatch):
    seen_call: dict[str, object] = {}
    seen_graph_call: dict[str, object] = {}
    expected_graph_input = GraphInput(
        session_id="session-from-adapter",
        documents=[NormalizedDocument(document_id="doc-from-adapter", markdown="适配后内容")],
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
        return ExtractionResult(
            broad_output=BroadExtractionOutput(
                fields=[
                    BroadExtractionFieldOutput(
                        field_name="invoice_no",
                        candidate_values=["INV-ADAPTER"],
                        evidence_texts=["发票号：INV-ADAPTER"],
                        local_status="candidate_found",
                    )
                ]
            ),
            resolved_fields=[
                ResolvedFieldOutput(
                    field_name="invoice_no",
                    status="resolved",
                    final_value="INV-ADAPTER",
                    used_field_outputs=["invoice_no"],
                    reason="图编排已完成",
                )
            ],
            run_trace=RunTrace(rounds=1),
        )

    monkeypatch.setattr(processor_module, "build_graph_input", fake_build_graph_input)
    monkeypatch.setattr(
        processor_module,
        "run_extraction_graph",
        fake_run_extraction_graph,
        raising=False,
    )

    result = processor_module.extract(
        session_id="session-raw",
        documents=[NormalizedDocument(document_id="doc-raw", markdown="原始输入")],
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

    assert seen_call["session_id"] == "session-raw"
    assert seen_call["metadata"] == {"source": "backend"}
    assert seen_graph_call["graph_input"] == expected_graph_input
    assert seen_graph_call["extractor_client"] is fake_client
    assert result.resolved_fields[0].final_value == "INV-ADAPTER"


def test_extract_delegates_execution_to_graph_with_built_client():
    seen_graph_call: dict[str, object] = {}
    fake_client = object()

    def fake_run_extraction_graph(*, graph_input, extractor_client):
        seen_graph_call["graph_input"] = graph_input
        seen_graph_call["extractor_client"] = extractor_client
        return ExtractionResult(
            broad_output=BroadExtractionOutput(
                fields=[
                    BroadExtractionFieldOutput(
                        field_name="invoice_no",
                        candidate_values=["INV-001"],
                        evidence_texts=["发票号码：INV-001"],
                        local_status="candidate_found",
                    )
                ]
            ),
            resolved_fields=[
                ResolvedFieldOutput(
                    field_name="invoice_no",
                    status="resolved",
                    final_value="INV-001",
                    used_field_outputs=["invoice_no"],
                    reason="图编排已完成",
                )
            ],
            run_trace=RunTrace(rounds=1),
        )

    processor_module.run_extraction_graph = fake_run_extraction_graph

    result = processor_module.extract(
        session_id="session-1",
        documents=[
            NormalizedDocument(
                document_id="doc-1",
                markdown="发票号码：INV-001",
                blocks=[NormalizedBlock(text="发票号码：INV-001", page_no=1)],
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
    assert seen_graph_call["graph_input"].session_id == "session-1"
    assert result.broad_output.fields[0].field_name == "invoice_no"
    assert result.resolved_fields[0].status == "resolved"
    assert result.resolved_fields[0].final_value == "INV-001"
    assert result.resolved_fields[0].used_field_outputs == ["invoice_no"]


def test_extract_passes_structured_output_strategy_to_client_builder(monkeypatch):
    seen_builder_call: dict[str, object] = {}
    fake_client = object()

    def fake_builder(*, structured_output_strategy):
        seen_builder_call["structured_output_strategy"] = structured_output_strategy
        return fake_client

    def fake_run_extraction_graph(*, graph_input, extractor_client):
        assert graph_input.session_id == "session-structured-output"
        assert extractor_client is fake_client
        return ExtractionResult(
            broad_output=BroadExtractionOutput(fields=[]),
            resolved_fields=[],
            run_trace=RunTrace(rounds=1),
        )

    monkeypatch.setattr(
        processor_module,
        "build_extractor_client_from_env",
        fake_builder,
    )
    monkeypatch.setattr(
        processor_module,
        "run_extraction_graph",
        fake_run_extraction_graph,
        raising=False,
    )

    processor_module.extract(
        session_id="session-structured-output",
        documents=[NormalizedDocument(document_id="doc-1", markdown="内容")],
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
        structured_output_strategy="json_schema",
    )

    assert seen_builder_call["structured_output_strategy"] == "json_schema"


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
        return ExtractionResult(
            broad_output=BroadExtractionOutput(fields=[]),
            resolved_fields=[
                ResolvedFieldOutput(
                    field_name="invoice_no",
                    status="failed",
                    used_field_outputs=["invoice_no"],
                    failure_reason="未找到可用候选值",
                )
            ],
            run_trace=RunTrace(rounds=1),
        )

    monkeypatch.setattr(
        processor_module,
        "run_extraction_graph",
        fake_run_extraction_graph,
        raising=False,
    )

    result = processor_module.extract(
        session_id="session-2",
        documents=[NormalizedDocument(document_id="doc-2", markdown="空白")],
        task_spec_name="invoice",
        extractor_client=object(),
    )

    assert result.resolved_fields[0].field_name == "invoice_no"
    assert result.resolved_fields[0].status == "failed"
    assert result.resolved_fields[0].failure_reason == "未找到可用候选值"


def test_extract_returns_graph_result_without_reimplementing_field_fill():
    def fake_run_extraction_graph(*, graph_input, extractor_client):
        del graph_input, extractor_client
        return ExtractionResult(
            broad_output=BroadExtractionOutput(fields=[]),
            resolved_fields=[
                ResolvedFieldOutput(
                    field_name="invoice_no",
                    status="resolved",
                    final_value="INV-003",
                    used_field_outputs=["invoice_no"],
                    reason="图编排已完成",
                ),
                ResolvedFieldOutput(
                    field_name="amount",
                    status="failed",
                    used_field_outputs=[],
                    failure_reason="未找到可用候选值",
                ),
            ],
            run_trace=RunTrace(rounds=1),
        )

    processor_module.run_extraction_graph = fake_run_extraction_graph

    result = processor_module.extract(
        session_id="session-3",
        documents=[NormalizedDocument(document_id="doc-3", markdown="只命中一个字段")],
        task_spec=TaskSpec(
            task_name="invoice",
            fields=[
                FieldDefinition(field_name="invoice_no", display_name="发票号", type="string"),
                FieldDefinition(field_name="amount", display_name="金额", type="money"),
            ],
        ),
        extractor_client=object(),
    )

    assert [field.field_name for field in result.resolved_fields] == [
        "invoice_no",
        "amount",
    ]
    assert result.resolved_fields[0].status == "resolved"
    assert result.resolved_fields[1].status == "failed"


def test_extract_rejects_missing_task_spec_and_task_spec_name():
    try:
        processor_module.extract(
            session_id="session-4",
            documents=[NormalizedDocument(document_id="doc-4", markdown="")],
        )
    except ValueError as exc:
        assert "task_spec" in str(exc)
    else:
        raise AssertionError("缺少 task_spec 和 task_spec_name 时应拒绝继续执行")
