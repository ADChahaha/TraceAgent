from pydantic import ValidationError

from file_extraction_agent.schemas import (
    BroadExtractionFieldOutput,
    BroadExtractionOutput,
    ExtractionResult,
    FieldDefinition,
    FieldEvidenceRef,
    GraphInput,
    NormalizedBlock,
    NormalizedBoundingBox,
    NormalizedDocument,
    ResolvedFieldOutput,
    RunConfig,
    RunTrace,
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
        session_id="session-1",
        documents=[
            NormalizedDocument(
                document_id="doc-1",
                markdown="# Title",
                blocks=[
                    NormalizedBlock(
                        text="发票号码：INV-001",
                        page_no=1,
                        bbox=NormalizedBoundingBox(x0=10, y0=20, x1=100, y1=40),
                        kind="text",
                        meta_info={"block_id": "b-1"},
                    )
                ],
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
    )

    assert graph_input.session_id == "session-1"
    assert graph_input.documents[0].document_id == "doc-1"
    assert graph_input.documents[0].md_list == []
    assert graph_input.documents[0].blocks[0].text == "发票号码：INV-001"
    assert graph_input.documents[0].blocks[0].bbox.x1 == 100
    assert graph_input.documents[0].blocks[0].meta_info["block_id"] == "b-1"
    assert graph_input.run_config.max_extra_lookups_per_field == 1
    assert graph_input.metadata == {}


def test_normalized_document_parses_serialized_blocks_into_structured_models():
    document = NormalizedDocument(
        document_id="doc-1",
        blocks=[
            {
                "text": "总金额：100.00",
                "page_no": 2,
                "bbox": {"x0": 1.0, "y0": 2.0, "x1": 3.0, "y1": 4.0},
                "kind": "table",
                "meta_info": {"row": 3},
            }
        ],
    )

    block = document.blocks[0]
    assert isinstance(block, NormalizedBlock)
    assert block.kind == "table"
    assert block.bbox is not None
    assert block.bbox.y1 == 4.0
    assert block.meta_info == {"row": 3}


def test_graph_input_requires_backend_session_id():
    try:
        GraphInput(
            documents=[NormalizedDocument(document_id="doc-1", markdown="# Title")],
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
        assert "session_id" in str(exc)
    else:
        raise AssertionError("GraphInput 必须携带 backend 聚合后的 session_id")


def test_broad_extraction_output_keeps_candidate_evidence_bundle():
    output = BroadExtractionOutput(
        fields=[
            BroadExtractionFieldOutput(
                field_name="invoice_no",
                candidate_values=["INV-001"],
                evidence_texts=["发票号码：INV-001"],
                evidence_refs=[
                    FieldEvidenceRef(document_id="doc-1", page=1, span="12:20", block_id="b-1")
                ],
                local_status="candidate_found",
                local_validation={"type": "pass"},
                local_notes=["格式符合预期"],
            )
        ]
    )

    field_output = output.fields[0]
    assert field_output.field_name == "invoice_no"
    assert field_output.candidate_values == ["INV-001"]
    assert field_output.evidence_refs[0].block_id == "b-1"
    assert field_output.local_notes == ["格式符合预期"]


def test_resolved_field_output_rejects_failed_status_with_final_value():
    try:
        ResolvedFieldOutput(
            field_name="invoice_no",
            status="failed",
            final_value="INV-001",
            failure_reason="证据冲突",
        )
    except ValidationError as exc:
        assert "final_value" in str(exc)
    else:
        raise AssertionError("failed 状态不应携带 final_value")


def test_resolved_field_output_requires_failure_reason_for_failed_status():
    try:
        ResolvedFieldOutput(field_name="invoice_no", status="failed")
    except ValidationError as exc:
        assert "failure_reason" in str(exc)
    else:
        raise AssertionError("failed 状态必须说明 failure_reason")


def test_extraction_result_aggregates_broad_output_and_resolved_fields():
    result = ExtractionResult(
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
                extra_lookup_used=False,
                reason="证据唯一且格式通过校验",
            )
        ],
        run_trace=RunTrace(rounds=1, warnings=["none"]),
    )

    payload = result.model_dump()

    assert payload["broad_output"]["fields"][0]["field_name"] == "invoice_no"
    assert payload["resolved_fields"][0]["status"] == "resolved"
    assert payload["run_trace"]["rounds"] == 1


def test_run_config_rejects_non_positive_lookup_limit():
    try:
        RunConfig(max_extra_lookups_per_field=0)
    except ValidationError as exc:
        assert "max_extra_lookups_per_field" in str(exc)
    else:
        raise AssertionError("max_extra_lookups_per_field 必须大于 0")
