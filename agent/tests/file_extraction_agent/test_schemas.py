from pydantic import ValidationError

from file_extraction_agent.schemas import (
    BroadExtractionOutput,
    BroadTrace,
    ExtractionContent,
    ExtractionResult,
    ExtractionTrace,
    FieldDefinition,
    FieldEvidenceBundle,
    FieldEvidenceRef,
    FieldTraceRecord,
    GraphInput,
    LookupTraceRecord,
    NormalizedBlock,
    NormalizedBoundingBox,
    NormalizedDocument,
    ResolvedFieldResult,
    RunConfig,
    TaskSpec,
)


def test_task_spec_rejects_duplicate_field_names():
    try:
        TaskSpec(
            task_name="invoice",
            fields=[
                FieldDefinition(field_name="amount", display_name="金额", type="money"),
                FieldDefinition(field_name="amount", display_name="金额2", type="money"),
            ],
        )
    except ValidationError as exc:
        assert "field_name" in str(exc)
    else:
        raise AssertionError("TaskSpec 应拒绝重复 field_name")


def test_graph_input_accepts_normalized_documents_with_safe_defaults():
    graph_input = GraphInput(
        blocks=[
            NormalizedBlock(
                document_id="doc-1",
                text="发票号码：INV-001",
                page_no=1,
                bbox=NormalizedBoundingBox(x0=10, y0=20, x1=100, y1=40),
                kind="text",
                meta_info={"block_id": "b-1"},
            )
        ],
        markdown="# Title",
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
    )

    assert graph_input.blocks[0].document_id == "doc-1"
    assert graph_input.md_list == []
    assert graph_input.blocks[0].text == "发票号码：INV-001"
    assert graph_input.blocks[0].bbox.x1 == 100
    assert graph_input.blocks[0].meta_info["block_id"] == "b-1"
    assert graph_input.run_config.max_extra_lookups_per_field == 1
    assert graph_input.metadata == {}


def test_graph_input_parses_serialized_blocks_into_structured_models():
    graph_input = GraphInput(
        blocks=[
            {
                "document_id": "doc-1",
                "text": "总金额：100.00",
                "page_no": 2,
                "bbox": {"x0": 1.0, "y0": 2.0, "x1": 3.0, "y1": 4.0},
                "kind": "table",
                "meta_info": {"row": 3},
            }
        ],
        task_spec=TaskSpec(
            task_name="invoice",
            fields=[
                FieldDefinition(
                    field_name="amount",
                    display_name="金额",
                    type="money",
                )
            ],
        ),
    )

    block = graph_input.blocks[0]
    assert isinstance(block, NormalizedBlock)
    assert block.document_id == "doc-1"
    assert block.kind == "table"
    assert block.bbox is not None
    assert block.bbox.y1 == 4.0
    assert block.meta_info == {"row": 3}


def test_graph_input_requires_blocks():
    try:
        GraphInput(
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
    except ValidationError as exc:
        assert "blocks" in str(exc)
    else:
        raise AssertionError("GraphInput 必须携带 blocks 主输入")


def test_field_evidence_bundle_keeps_relevant_blocks_and_evidence():
    output = BroadExtractionOutput(
        fields=[
            FieldEvidenceBundle(
                field_name="invoice_no",
                relevant_block_ids=["b-1", "b-2"],
                evidence_texts=["发票号码：INV-001"],
                evidence_refs=[
                    FieldEvidenceRef(document_id="doc-1", page=1, span="12:20", block_id="b-1")
                ],
                local_status="evidence_found",
                local_notes=["页眉处命中字段关键词"],
            )
        ]
    )

    field_output = output.fields[0]
    assert field_output.field_name == "invoice_no"
    assert field_output.relevant_block_ids == ["b-1", "b-2"]
    assert field_output.evidence_refs[0].block_id == "b-1"
    assert field_output.local_notes == ["页眉处命中字段关键词"]


def test_resolved_field_result_rejects_failed_status_with_final_value():
    try:
        ResolvedFieldResult(
            field_name="invoice_no",
            status="failed",
            final_value="INV-001",
        )
    except ValidationError as exc:
        assert "final_value" in str(exc)
    else:
        raise AssertionError("failed 状态不应携带 final_value")


def test_field_trace_record_requires_reason_or_failure_reason_by_status():
    try:
        FieldTraceRecord(
            field_name="invoice_no",
            status="resolved",
            broad_trace=BroadTrace(local_status="evidence_found"),
        )
    except ValidationError as exc:
        assert "reason" in str(exc)
    else:
        raise AssertionError("resolved trace 必须说明定案原因")

    try:
        FieldTraceRecord(
            field_name="invoice_no",
            status="failed",
            broad_trace=BroadTrace(local_status="evidence_missing"),
        )
    except ValidationError as exc:
        assert "failure_reason" in str(exc)
    else:
        raise AssertionError("failed trace 必须说明失败原因")


def test_extraction_result_separates_result_and_trace():
    result = ExtractionResult(
        result=ExtractionContent(
            fields=[
                ResolvedFieldResult(
                    field_name="invoice_no",
                    status="resolved",
                    final_value="INV-001",
                )
            ]
        ),
        trace=ExtractionTrace(
            fields=[
                FieldTraceRecord(
                    field_name="invoice_no",
                    status="resolved",
                    broad_trace=BroadTrace(
                        relevant_block_ids=["b-1"],
                        evidence_texts=["发票号码：INV-001"],
                        local_status="evidence_found",
                    ),
                    used_field_outputs=["invoice_no"],
                    extra_lookup_used=False,
                    lookup_trace=[
                        LookupTraceRecord(
                            lookup_reason="无须补查，仅验证序列化结构",
                            returned_block_ids=["b-1"],
                        )
                    ],
                    reason="证据充分，字段可定案",
                )
            ],
            warnings=["none"],
        ),
    )

    payload = result.model_dump()

    assert payload["result"]["fields"][0]["field_name"] == "invoice_no"
    assert payload["trace"]["fields"][0]["broad_trace"]["local_status"] == "evidence_found"
    assert payload["trace"]["warnings"] == ["none"]


def test_run_config_rejects_non_positive_lookup_limit():
    try:
        RunConfig(max_extra_lookups_per_field=0)
    except ValidationError as exc:
        assert "max_extra_lookups_per_field" in str(exc)
    else:
        raise AssertionError("max_extra_lookups_per_field 必须大于 0")
