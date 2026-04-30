from pydantic import ValidationError

from service.file_extraction_agent.impl.schemas import (
    BroadAction,
    Candidate,
    ExtractionInput,
    FieldDecision,
    FieldResolutionAction,
    SearchResult,
    ToolActionRecord,
)
from service.file_extraction_agent.schemas import (
    EvidenceSummary,
    ExtractionContent,
    ExtractionResult,
    ExtractionTrace,
    FieldDefinition,
    FieldResult,
    FieldTrace,
    NormalizedBlock,
    NormalizedBoundingBox,
    NormalizedDocument,
    RunOptions,
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


def test_task_spec_accepts_list_field_and_resolution_value_list():
    task_spec = TaskSpec(
        task_name="academic_paper_extraction",
        fields=[
            FieldDefinition(
                field_name="academic_paper_titles",
                display_name="学术论文名称",
                type="list",
                required=True,
            )
        ],
    )
    action = FieldResolutionAction(
        action="final_decision",
        field_name="academic_paper_titles",
        status="resolved",
        value=["论文 A", "论文 B"],
        candidate_ids=["c1"],
        reason="模型按原文顺序抽取出两篇学术论文",
    )

    assert task_spec.fields[0].type == "list"
    assert action.value == ["论文 A", "论文 B"]


def test_extraction_input_accepts_blocks_with_safe_defaults():
    extraction_input = ExtractionInput(
        blocks=[
            NormalizedBlock(
                document_id="doc-1",
                block_id="b-1",
                text="发票号码：INV-001",
                page_no=1,
                bbox=NormalizedBoundingBox(x0=10, y0=20, x1=100, y1=40),
                kind="text",
                meta_info={"source": "docling"},
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
    assert extraction_input.options.max_prompt_blocks == 200
    assert extraction_input.options.max_prompt_block_chars == 2000
    assert extraction_input.options.max_resolution_candidates == 20
    assert extraction_input.metadata == {}


def test_internal_tool_and_candidate_schemas_keep_refs_separate_from_candidates():
    search_result = SearchResult(ref="b-1:p:p1", text="发票号：INV-001")
    candidate = Candidate(
        candidate_id="c1",
        field_name="invoice_no",
        source_stage="broad",
        ref=search_result.ref,
        text=search_result.text,
        reason="命中发票号",
    )
    action = ToolActionRecord(
        field_name="invoice_no",
        stage="broad",
        action_type="add_broad_candidate",
        refs=[search_result.ref],
        candidate_ids=[candidate.candidate_id],
    )

    assert candidate.ref == "b-1:p:p1"
    assert candidate.candidate_id == "c1"
    assert action.refs == ["b-1:p:p1"]
    assert action.candidate_ids == ["c1"]


def test_broad_action_validates_terminal_finish_shape():
    action = BroadAction(
        action="finish_broad",
        field_name="invoice_no",
        status="partial_evidence",
        reason="只找到部分证据",
    )

    assert action.status == "partial_evidence"

    try:
        BroadAction(action="finish_broad", field_name="invoice_no")
    except ValidationError as exc:
        assert "finish_broad action requires status and reason" in str(exc)
    else:
        raise AssertionError("finish_broad 必须声明 status 和 reason")


def test_field_decision_requires_candidate_ids_for_resolved_status():
    try:
        FieldDecision(
            field_name="invoice_no",
            status="resolved",
            value="INV-001",
            reason="缺少候选 id",
        )
    except ValidationError as exc:
        assert "resolved decision requires candidate_ids" in str(exc)
    else:
        raise AssertionError("resolved 字段必须引用候选证据")


def test_extraction_input_parses_serialized_blocks_into_structured_models():
    extraction_input = ExtractionInput(
        blocks=[
            {
                "document_id": "doc-1",
                "block_id": "b-table",
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
                            action_type="text_grep",
                            message="检索发票号",
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
    assert payload["trace"]["fields"][0]["actions"][0]["action_type"] == "text_grep"
    assert NormalizedDocument(document_id="doc-1").markdown == ""
