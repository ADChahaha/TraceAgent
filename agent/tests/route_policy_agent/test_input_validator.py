from __future__ import annotations

from service.file_extraction_agent.schemas import FieldDefinition, TaskSpec
from service.route_policy_agent.input_validator import (
    RoutePolicyInputError,
    validate_route_policy_input,
)
from service.route_policy_agent.schemas import (
    EvidenceTextRef,
    FieldRefsWithText,
    RouteFieldOutput,
    RoutePolicyInput,
)


def _task_spec() -> TaskSpec:
    return TaskSpec(
        task_name="invoice",
        fields=[
            FieldDefinition(
                field_name="invoice_no",
                display_name="发票号",
                type="string",
                required=True,
            )
        ],
    )


def _valid_input() -> RoutePolicyInput:
    return RoutePolicyInput(
        task_spec=_task_spec(),
        field_outputs=[
            RouteFieldOutput(
                field_name="invoice_no",
                status="resolved",
                value="INV-001",
            )
        ],
        refs_with_text=[
            FieldRefsWithText(
                field_name="invoice_no",
                refs=[
                    EvidenceTextRef(
                        document_id="doc-1",
                        page=1,
                        block_id="b1",
                        text="发票号码：INV-001",
                    )
                ],
            )
        ],
    )


def test_validate_route_policy_input_builds_field_indexes():
    validated = validate_route_policy_input(_valid_input())

    assert validated.field_definitions_by_name["invoice_no"].display_name == "发票号"
    assert validated.field_outputs_by_name["invoice_no"].value == "INV-001"
    assert validated.refs_by_field_name["invoice_no"][0].text == "发票号码：INV-001"


def test_validate_route_policy_input_rejects_unknown_field_output():
    route_input = _valid_input().model_copy(
        update={
            "field_outputs": [
                RouteFieldOutput(
                    field_name="unknown",
                    status="resolved",
                    value="INV-001",
                )
            ]
        }
    )

    try:
        validate_route_policy_input(route_input)
    except RoutePolicyInputError as exc:
        assert "unknown field_output.field_name: unknown" in str(exc)
    else:
        raise AssertionError("未知字段输出应被拒绝")


def test_validate_route_policy_input_requires_refs_group_for_every_field_output():
    route_input = _valid_input().model_copy(update={"refs_with_text": []})

    try:
        validate_route_policy_input(route_input)
    except RoutePolicyInputError as exc:
        assert "missing refs_with_text for field: invoice_no" in str(exc)
    else:
        raise AssertionError("每个待评估字段都必须有 refs_with_text 分组")


def test_validate_route_policy_input_rejects_resolved_field_without_ref_text():
    route_input = _valid_input().model_copy(
        update={
            "refs_with_text": [
                FieldRefsWithText(
                    field_name="invoice_no",
                    refs=[
                        EvidenceTextRef(
                            document_id="doc-1",
                            page=1,
                            text="   ",
                        )
                    ],
                )
            ]
        }
    )

    try:
        validate_route_policy_input(route_input)
    except RoutePolicyInputError as exc:
        assert "invoice_no refs_with_text[0].text is required" in str(exc)
    else:
        raise AssertionError("ref 缺少证据文本时应被拒绝")


def test_validate_route_policy_input_rejects_ref_without_source_location():
    route_input = _valid_input().model_copy(
        update={
            "refs_with_text": [
                FieldRefsWithText(
                    field_name="invoice_no",
                    refs=[EvidenceTextRef(text="发票号码：INV-001")],
                )
            ]
        }
    )

    try:
        validate_route_policy_input(route_input)
    except RoutePolicyInputError as exc:
        assert "invoice_no refs_with_text[0] source location is required" in str(exc)
    else:
        raise AssertionError("ref 只有文本、没有来源位置时应被拒绝")
