from pydantic import ValidationError

from service.file_extraction_agent.impl.schemas import (
    EvidenceCollection,
    ExtractionInput,
    FieldDecision,
    FieldEvidence,
    FieldResolutionAction,
    FieldResolutionDecision,
    LookupRecord,
    RunOptions,
)
from service.file_extraction_agent.schemas import (
    EvidenceSummary,
    ExtractionContent,
    ExtractionResult,
    ExtractionTrace,
    FieldDefinition,
    FieldEvidenceRef,
    FieldResult,
    FieldTrace,
    NormalizedBlock,
    NormalizedBoundingBox,
    NormalizedDocument,
    TaskSpec,
    TraceAction,
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


def test_extraction_input_accepts_blocks_with_safe_defaults():
    extraction_input = ExtractionInput(
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

    assert extraction_input.blocks[0].document_id == "doc-1"
    assert extraction_input.md_list == []
    assert extraction_input.blocks[0].bbox.x1 == 100
    assert extraction_input.options.max_lookup_calls_per_field == 1
    assert extraction_input.options.lookup_top_k == 3
    assert extraction_input.options.max_prompt_blocks == 200
    assert extraction_input.options.max_prompt_block_chars == 2000
    assert extraction_input.metadata == {}


def test_extraction_input_parses_serialized_blocks_into_structured_models():
    extraction_input = ExtractionInput(
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

    block = extraction_input.blocks[0]
    assert isinstance(block, NormalizedBlock)
    assert block.document_id == "doc-1"
    assert block.kind == "table"
    assert block.bbox is not None
    assert block.bbox.y1 == 4.0
    assert block.meta_info == {"row": 3}


def test_extraction_input_requires_blocks():
    try:
        ExtractionInput(
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
        raise AssertionError("ExtractionInput 必须携带 blocks 主输入")


def test_field_evidence_keeps_relevant_blocks_and_evidence():
    evidence_collection = EvidenceCollection(
        fields=[
            FieldEvidence(
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

    field_evidence = evidence_collection.fields[0]
    assert field_evidence.field_name == "invoice_no"
    assert field_evidence.relevant_block_ids == ["b-1", "b-2"]
    assert field_evidence.evidence_refs[0].block_id == "b-1"
    assert field_evidence.local_notes == ["页眉处命中字段关键词"]


def test_field_result_rejects_failed_status_with_value():
    try:
        FieldResult(
            field_name="invoice_no",
            status="failed",
            value="INV-001",
        )
    except ValidationError as exc:
        assert "value" in str(exc)
    else:
        raise AssertionError("failed 状态不应携带 value")


def test_field_trace_requires_reason_or_failure_reason_by_status():
    try:
        FieldTrace(
            field_name="invoice_no",
            status="resolved",
            evidence=EvidenceSummary(status="evidence_found"),
        )
    except ValidationError as exc:
        assert "reason" in str(exc)
    else:
        raise AssertionError("resolved trace 必须说明定案原因")

    try:
        FieldTrace(
            field_name="invoice_no",
            status="failed",
            evidence=EvidenceSummary(status="missing"),
        )
    except ValidationError as exc:
        assert "failure_reason" in str(exc)
    else:
        raise AssertionError("failed trace 必须说明失败原因")


def test_extraction_result_separates_result_and_trace():
    result = ExtractionResult(
        result=ExtractionContent(
            fields=[
                FieldResult(
                    field_name="invoice_no",
                    status="resolved",
                    value="INV-001",
                )
            ]
        ),
        trace=ExtractionTrace(
            fields=[
                FieldTrace(
                    field_name="invoice_no",
                    status="resolved",
                    evidence=EvidenceSummary(
                        block_ids=["b-1"],
                        texts=["发票号码：INV-001"],
                        status="evidence_found",
                    ),
                    related_fields=["invoice_no"],
                    actions=[
                        TraceAction(
                            action_type="global_lookup",
                            message="无须补查，仅验证序列化结构",
                            used_in_final_decision=False,
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
    assert payload["trace"]["fields"][0]["evidence"]["status"] == "evidence_found"
    assert payload["trace"]["warnings"] == ["none"]
    assert payload["status"] == "completed"


def test_failed_extraction_result_requires_failure_reason():
    try:
        ExtractionResult(
            status="failed",
            result=ExtractionContent(fields=[]),
            trace=ExtractionTrace(fields=[]),
        )
    except ValidationError as exc:
        assert "failure_reason" in str(exc)
    else:
        raise AssertionError("整包 failed 返回必须说明统一失败原因")

    result = ExtractionResult(
        status="failed",
        failure_reason="resolution 执行失败: RuntimeError: api timeout",
        result=ExtractionContent(fields=[]),
        trace=ExtractionTrace(fields=[]),
    )

    assert result.failure_reason == "resolution 执行失败: RuntimeError: api timeout"


def test_run_options_reject_non_positive_lookup_limits():
    try:
        RunOptions(max_lookup_calls_per_field=0)
    except ValidationError as exc:
        assert "max_lookup_calls_per_field" in str(exc)
    else:
        raise AssertionError("max_lookup_calls_per_field 必须大于 0")

    try:
        RunOptions(lookup_top_k=0)
    except ValidationError as exc:
        assert "lookup_top_k" in str(exc)
    else:
        raise AssertionError("lookup_top_k 必须大于 0")

    try:
        RunOptions(max_prompt_blocks=0)
    except ValidationError as exc:
        assert "max_prompt_blocks" in str(exc)
    else:
        raise AssertionError("max_prompt_blocks 必须大于 0")


def test_field_decision_rejects_failed_status_with_value():
    try:
        FieldDecision(
            field_name="invoice_no",
            status="failed",
            value="INV-001",
            evidence=FieldEvidence(field_name="invoice_no", local_status="missing"),
        )
    except ValidationError as exc:
        assert "value" in str(exc)
    else:
        raise AssertionError("内部 failed 决策不应携带 value")


def test_field_resolution_action_uses_lightweight_model_decision():
    action = FieldResolutionAction(
        action="final_decision",
        target_field_name="amount",
        decision=FieldResolutionDecision(
            status="resolved",
            value="100.00",
            used_block_ids=["b-amount"],
            related_fields=["invoice_no"],
            reason="模型判断金额字段证据充分",
        ),
    )

    assert action.decision is not None
    assert action.decision.used_block_ids == ["b-amount"]
    assert not hasattr(action.decision, "evidence")


def test_field_resolution_action_value_schema_is_strict_provider_compatible():
    schema = FieldResolutionAction.model_json_schema()
    value_schema = schema["$defs"]["FieldResolutionDecision"]["properties"]["value"]

    assert value_schema["anyOf"]
    assert all("type" in branch for branch in value_schema["anyOf"])


def test_lookup_record_can_be_projected_to_trace_action():
    record = LookupRecord(
        target_field_name="amount",
        lookup_reason="需要补查金额字段",
        lookup_hints=["amount", "total"],
        returned_block_ids=["b-1"],
        returned_refs=[FieldEvidenceRef(document_id="doc-1", block_id="b-1")],
        returned_to_model=True,
        used_in_final_decision=False,
    )

    action = record.to_trace_action()

    assert action.action_type == "global_lookup"
    assert action.refs[0].block_id == "b-1"
    assert action.used_in_final_decision is False
    assert action.metadata["target_field_name"] == "amount"
    assert action.metadata["returned_block_ids"] == ["b-1"]
    assert action.metadata["returned_to_model"] is True
