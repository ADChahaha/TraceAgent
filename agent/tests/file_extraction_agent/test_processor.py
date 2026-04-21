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
    TaskSpec,
)


def test_extract_delegates_graph_input_building_to_input_adapter(monkeypatch):
    seen_call: dict[str, object] = {}
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

    class FakeExtractorClient:
        def invoke(self, *, output_schema, messages):
            assert output_schema is BroadExtractionOutput
            assert "session-from-adapter" in messages[1]["content"]
            return BroadExtractionOutput(
                fields=[
                    BroadExtractionFieldOutput(
                        field_name="invoice_no",
                        candidate_values=["INV-ADAPTER"],
                        evidence_texts=["发票号：INV-ADAPTER"],
                        local_status="candidate_found",
                    )
                ]
            )

    monkeypatch.setattr(processor_module, "build_graph_input", fake_build_graph_input)

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
        extractor_client=FakeExtractorClient(),
    )

    assert seen_call["session_id"] == "session-raw"
    assert seen_call["metadata"] == {"source": "backend"}
    assert result.resolved_fields[0].final_value == "INV-ADAPTER"


def test_extract_builds_graph_input_from_prevalidated_documents_and_task_spec():
    seen_call: dict[str, object] = {}

    class FakeExtractorClient:
        def invoke(self, *, output_schema, messages):
            seen_call["output_schema"] = output_schema
            seen_call["messages"] = messages
            return BroadExtractionOutput(
                fields=[
                    BroadExtractionFieldOutput(
                        field_name="invoice_no",
                        candidate_values=["INV-001"],
                        evidence_texts=["发票号码：INV-001"],
                        local_status="candidate_found",
                    )
                ]
            )

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
        extractor_client=FakeExtractorClient(),
    )

    assert isinstance(result, ExtractionResult)
    assert seen_call["output_schema"] is BroadExtractionOutput
    assert isinstance(seen_call["messages"], list)
    assert result.broad_output.fields[0].field_name == "invoice_no"
    assert result.resolved_fields[0].status == "resolved"
    assert result.resolved_fields[0].final_value == "INV-001"
    assert result.resolved_fields[0].used_field_outputs == ["invoice_no"]


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

    class FakeExtractorClient:
        def invoke(self, *, output_schema, messages):
            del output_schema, messages
            return BroadExtractionOutput(
                fields=[
                    BroadExtractionFieldOutput(
                        field_name="invoice_no",
                        candidate_values=[],
                        evidence_texts=[],
                        local_status="missing",
                    )
                ]
            )

    result = processor_module.extract(
        session_id="session-2",
        documents=[NormalizedDocument(document_id="doc-2", markdown="空白")],
        task_spec_name="invoice",
        extractor_client=FakeExtractorClient(),
    )

    assert result.resolved_fields[0].field_name == "invoice_no"
    assert result.resolved_fields[0].status == "failed"
    assert result.resolved_fields[0].failure_reason == "未找到可用候选值"


def test_extract_uses_task_spec_order_to_fill_missing_field_outputs():
    class FakeExtractorClient:
        def invoke(self, *, output_schema, messages):
            del output_schema, messages
            return BroadExtractionOutput(
                fields=[
                    BroadExtractionFieldOutput(
                        field_name="invoice_no",
                        candidate_values=["INV-003"],
                        evidence_texts=["发票号：INV-003"],
                        local_status="candidate_found",
                    )
                ]
            )

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
        extractor_client=FakeExtractorClient(),
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
