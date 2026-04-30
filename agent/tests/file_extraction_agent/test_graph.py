from __future__ import annotations

from service.file_extraction_agent.impl.schemas import (
    BroadFinishRecord,
    Candidate,
    ExtractionInput,
    FieldDecision,
)
from service.file_extraction_agent.schemas import (
    EvidenceSummary,
    ExtractionResult,
    FieldDefinition,
    NormalizedBlock,
    TaskSpec,
)


def _build_extraction_input() -> ExtractionInput:
    return ExtractionInput(
        blocks=[
            NormalizedBlock(document_id="doc-1", block_id="b-invoice", text="发票号：INV-900"),
            NormalizedBlock(document_id="doc-1", block_id="b-amount", text="金额：300.00"),
        ],
        task_spec=TaskSpec(
            task_name="invoice",
            fields=[
                FieldDefinition(
                    field_name="invoice_no",
                    display_name="发票号",
                    type="string",
                    required=True,
                ),
                FieldDefinition(
                    field_name="amount",
                    display_name="金额",
                    type="money",
                    required=True,
                ),
            ],
        ),
    )


def test_run_extraction_graph_runs_broad_stage_then_resolution_stage(monkeypatch):
    from service.file_extraction_agent.impl import graph as graph_module

    extraction_input = _build_extraction_input()
    call_order: list[str] = []

    def fake_run_broad_stage(*, state, extractor_client):
        assert extractor_client == "fake-client"
        call_order.append("broad")
        state.candidates["invoice_no"] = [
            Candidate(
                candidate_id="c1",
                field_name="invoice_no",
                source_stage="broad",
                ref="b-invoice:p:p1",
                text="发票号：INV-900",
                reason="测试候选",
            )
        ]
        return state

    def fake_run_resolution_stage(*, state, extractor_client):
        assert extractor_client == "fake-client"
        call_order.append("resolution")
        state.field_decisions["invoice_no"] = FieldDecision(
            field_name="invoice_no",
            status="resolved",
            value="INV-900",
            candidate_ids=["c1"],
            reason="候选证据支持字段值",
        )
        state.field_decisions["amount"] = FieldDecision(
            field_name="amount",
            status="failed",
            failure_reason="缺少金额候选",
        )
        state.warnings.append("resolution-ran")
        return state

    monkeypatch.setattr(graph_module, "run_broad_stage", fake_run_broad_stage)
    monkeypatch.setattr(graph_module, "run_resolution_stage", fake_run_resolution_stage)

    result = graph_module.run_extraction_graph(
        extraction_input=extraction_input,
        extractor_client="fake-client",
    )

    assert call_order == ["broad", "resolution"]
    assert isinstance(result, ExtractionResult)
    assert result.status == "completed"
    assert result.result.fields[0].field_name == "invoice_no"
    assert result.result.fields[0].value == "INV-900"
    assert result.trace.fields[0].evidence.block_ids == ["b-invoice"]
    assert result.trace.warnings == ["resolution-ran"]


def test_run_extraction_graph_can_use_distinct_stage_clients(monkeypatch):
    from service.file_extraction_agent.impl import graph as graph_module

    extraction_input = _build_extraction_input()
    broad_client = object()
    resolution_client = object()
    seen_clients: list[object] = []

    def fake_run_broad_stage(*, state, extractor_client):
        seen_clients.append(extractor_client)
        state.candidates["invoice_no"] = [
            Candidate(
                candidate_id="c1",
                field_name="invoice_no",
                source_stage="broad",
                ref="b-invoice:p:p1",
                text="发票号：INV-900",
                reason="测试候选",
            )
        ]
        return state

    def fake_run_resolution_stage(*, state, extractor_client):
        seen_clients.append(extractor_client)
        state.field_decisions["invoice_no"] = FieldDecision(
            field_name="invoice_no",
            status="resolved",
            value="INV-900",
            candidate_ids=["c1"],
            reason="候选证据支持字段值",
        )
        state.field_decisions["amount"] = FieldDecision(
            field_name="amount",
            status="failed",
            failure_reason="缺少金额候选",
        )
        return state

    monkeypatch.setattr(graph_module, "run_broad_stage", fake_run_broad_stage)
    monkeypatch.setattr(graph_module, "run_resolution_stage", fake_run_resolution_stage)

    result = graph_module.run_extraction_graph(
        extraction_input=extraction_input,
        broad_extractor_client=broad_client,
        resolution_extractor_client=resolution_client,
    )

    assert seen_clients == [broad_client, resolution_client]
    assert result.status == "completed"


def test_map_state_to_result_resolves_candidate_refs_to_external_trace():
    from service.file_extraction_agent.impl.graph import map_state_to_result
    from service.file_extraction_agent.impl.state import build_graph_state
    from service.file_extraction_agent.impl.tools.candidates import add_broad_candidate

    state = build_graph_state(_build_extraction_input())
    add_broad_candidate(
        state=state,
        field_name="invoice_no",
        refs=["b-invoice:p:p1"],
        reason="命中发票号段落",
    )
    state.field_decisions["invoice_no"] = FieldDecision(
        field_name="invoice_no",
        status="resolved",
        value="INV-900",
        candidate_ids=["c1"],
        related_fields=["invoice_no"],
        reason="候选证据支持字段值",
    )
    state.field_decisions["amount"] = FieldDecision(
        field_name="amount",
        status="failed",
        failure_reason="未找到金额候选",
    )

    result = map_state_to_result(state)

    assert [field.field_name for field in result.result.fields] == ["invoice_no", "amount"]
    assert result.result.fields[0].value == "INV-900"
    assert isinstance(result.trace.fields[0].evidence, EvidenceSummary)
    assert result.trace.fields[0].evidence.block_ids == ["b-invoice"]
    assert result.trace.fields[0].evidence.refs[0].document_id == "doc-1"
    assert result.trace.fields[0].actions[0].action_type == "add_broad_candidate"
    assert result.trace.fields[1].failure_reason == "未找到金额候选"


def test_run_extraction_graph_returns_failed_result_when_broad_fails(monkeypatch):
    from service.file_extraction_agent.impl import graph as graph_module

    extraction_input = _build_extraction_input()

    def fake_run_broad_stage(*, state, extractor_client):
        del state, extractor_client
        raise RuntimeError("upstream api timeout")

    monkeypatch.setattr(graph_module, "run_broad_stage", fake_run_broad_stage)

    result = graph_module.run_extraction_graph(
        extraction_input=extraction_input,
        extractor_client="fake-client",
    )

    assert result.status == "failed"
    assert "upstream api timeout" in result.failure_reason
    assert [field.status for field in result.result.fields] == ["failed", "failed"]
    assert result.trace.metadata["failure_stage"] == "broad"
    assert result.trace.fields[0].actions[0].action_type == "model_call_error"
    assert result.trace.fields[0].actions[0].metadata["error_type"] == "RuntimeError"


def test_broad_failure_action_is_attached_to_first_unfinished_broad_field(monkeypatch):
    from service.file_extraction_agent.impl import graph as graph_module
    from service.file_extraction_agent.impl.state import record_action
    from service.file_extraction_agent.impl.schemas import ToolActionRecord

    extraction_input = _build_extraction_input()

    def fake_run_broad_stage(*, state, extractor_client):
        del extractor_client
        state.broad_finishes["invoice_no"] = BroadFinishRecord(
            field_name="invoice_no",
            status="enough_evidence",
            reason="发票号 broad 已完成",
        )
        record_action(
            state,
            field_name="invoice_no",
            action=ToolActionRecord(
                field_name="invoice_no",
                stage="broad",
                action_type="finish_broad",
                message="发票号 broad 已完成",
            ),
        )
        raise RuntimeError("amount broad failed")

    monkeypatch.setattr(graph_module, "run_broad_stage", fake_run_broad_stage)

    result = graph_module.run_extraction_graph(
        extraction_input=extraction_input,
        extractor_client="fake-client",
    )

    actions_by_field = {
        field_trace.field_name: [action.action_type for action in field_trace.actions]
        for field_trace in result.trace.fields
    }

    assert actions_by_field["invoice_no"] == ["finish_broad"]
    assert actions_by_field["amount"] == ["model_call_error"]
    assert result.trace.metadata["completed_field_names"] == ["invoice_no"]
    assert result.trace.metadata["pending_field_names"] == ["amount"]


def test_run_extraction_graph_preserves_completed_decisions_before_resolution_failure(monkeypatch):
    from service.file_extraction_agent.impl import graph as graph_module

    extraction_input = _build_extraction_input()

    def fake_run_broad_stage(*, state, extractor_client):
        del extractor_client
        state.candidates["invoice_no"] = [
            Candidate(
                candidate_id="c1",
                field_name="invoice_no",
                source_stage="broad",
                ref="b-invoice:p:p1",
                text="发票号：INV-900",
                reason="已找到发票号",
            )
        ]
        return state

    def fake_run_resolution_stage(*, state, extractor_client):
        del extractor_client
        state.field_decisions["invoice_no"] = FieldDecision(
            field_name="invoice_no",
            status="resolved",
            value="INV-900",
            candidate_ids=["c1"],
            reason="发票号字段已在失败前完成定案",
        )
        raise RuntimeError("resolution api quota exceeded")

    monkeypatch.setattr(graph_module, "run_broad_stage", fake_run_broad_stage)
    monkeypatch.setattr(graph_module, "run_resolution_stage", fake_run_resolution_stage)

    result = graph_module.run_extraction_graph(
        extraction_input=extraction_input,
        extractor_client="fake-client",
    )

    assert result.status == "failed"
    assert [field.field_name for field in result.result.fields] == ["invoice_no", "amount"]
    assert result.result.fields[0].status == "resolved"
    assert result.result.fields[0].value == "INV-900"
    assert result.result.fields[1].status == "failed"
    assert result.trace.fields[1].actions[0].action_type == "model_call_error"
    assert result.trace.metadata["failure_stage"] == "resolution"
