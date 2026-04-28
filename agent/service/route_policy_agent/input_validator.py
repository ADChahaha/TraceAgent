"""route policy 输入的跨对象一致性校验。"""

from __future__ import annotations

from dataclasses import dataclass

from service.file_extraction_agent.schemas import FieldDefinition
from service.route_policy_agent.schemas import (
    EvidenceTextRef,
    RouteFieldOutput,
    RoutePolicyInput,
)


class RoutePolicyInputError(ValueError):
    """route policy 输入协议不完整或不一致时抛出。"""


@dataclass(frozen=True, slots=True)
class ValidatedPolicyInput:
    """校验后的 route policy 输入索引。"""

    route_input: RoutePolicyInput
    field_definitions_by_name: dict[str, FieldDefinition]
    field_outputs_by_name: dict[str, RouteFieldOutput]
    refs_by_field_name: dict[str, list[EvidenceTextRef]]


def validate_route_policy_input(route_input: RoutePolicyInput) -> ValidatedPolicyInput:
    """校验字段定义、字段输出和 refs 文本是否能一一对齐。"""

    field_definitions_by_name = {
        field.field_name: field
        for field in route_input.task_spec.fields
    }
    field_outputs_by_name = _index_unique_field_outputs(route_input)
    refs_by_field_name = _index_unique_refs(route_input)

    _validate_field_outputs_known(
        field_outputs_by_name=field_outputs_by_name,
        field_definitions_by_name=field_definitions_by_name,
    )
    _validate_refs_known_and_requested(
        refs_by_field_name=refs_by_field_name,
        field_definitions_by_name=field_definitions_by_name,
        field_outputs_by_name=field_outputs_by_name,
    )
    _validate_refs_complete(
        field_outputs_by_name=field_outputs_by_name,
        refs_by_field_name=refs_by_field_name,
    )

    return ValidatedPolicyInput(
        route_input=route_input,
        field_definitions_by_name=field_definitions_by_name,
        field_outputs_by_name=field_outputs_by_name,
        refs_by_field_name=refs_by_field_name,
    )


def _index_unique_field_outputs(
    route_input: RoutePolicyInput,
) -> dict[str, RouteFieldOutput]:
    indexed: dict[str, RouteFieldOutput] = {}
    duplicated: set[str] = set()
    for field_output in route_input.field_outputs:
        if field_output.field_name in indexed:
            duplicated.add(field_output.field_name)
        indexed[field_output.field_name] = field_output
    if duplicated:
        duplicated_names = ", ".join(sorted(duplicated))
        raise RoutePolicyInputError(f"duplicated field_output.field_name: {duplicated_names}")
    return indexed


def _index_unique_refs(route_input: RoutePolicyInput) -> dict[str, list[EvidenceTextRef]]:
    indexed: dict[str, list[EvidenceTextRef]] = {}
    duplicated: set[str] = set()
    for refs_group in route_input.refs_with_text:
        if refs_group.field_name in indexed:
            duplicated.add(refs_group.field_name)
        indexed[refs_group.field_name] = refs_group.refs
    if duplicated:
        duplicated_names = ", ".join(sorted(duplicated))
        raise RoutePolicyInputError(f"duplicated refs_with_text.field_name: {duplicated_names}")
    return indexed


def _validate_field_outputs_known(
    *,
    field_outputs_by_name: dict[str, RouteFieldOutput],
    field_definitions_by_name: dict[str, FieldDefinition],
) -> None:
    unknown_names = [
        field_name
        for field_name in field_outputs_by_name
        if field_name not in field_definitions_by_name
    ]
    if unknown_names:
        raise RoutePolicyInputError(
            f"unknown field_output.field_name: {', '.join(sorted(unknown_names))}"
        )


def _validate_refs_known_and_requested(
    *,
    refs_by_field_name: dict[str, list[EvidenceTextRef]],
    field_definitions_by_name: dict[str, FieldDefinition],
    field_outputs_by_name: dict[str, RouteFieldOutput],
) -> None:
    unknown_ref_names = [
        field_name
        for field_name in refs_by_field_name
        if field_name not in field_definitions_by_name
    ]
    if unknown_ref_names:
        raise RoutePolicyInputError(
            f"unknown refs_with_text.field_name: {', '.join(sorted(unknown_ref_names))}"
        )

    unexpected_ref_names = [
        field_name
        for field_name in refs_by_field_name
        if field_name not in field_outputs_by_name
    ]
    if unexpected_ref_names:
        raise RoutePolicyInputError(
            "unexpected refs_with_text.field_name without field_output: "
            f"{', '.join(sorted(unexpected_ref_names))}"
        )


def _validate_refs_complete(
    *,
    field_outputs_by_name: dict[str, RouteFieldOutput],
    refs_by_field_name: dict[str, list[EvidenceTextRef]],
) -> None:
    for field_name, field_output in field_outputs_by_name.items():
        if field_name not in refs_by_field_name:
            raise RoutePolicyInputError(f"missing refs_with_text for field: {field_name}")

        refs = refs_by_field_name[field_name]
        if field_output.status == "resolved" and not refs:
            raise RoutePolicyInputError(
                f"{field_name} refs_with_text is required for resolved field"
            )

        for index, ref in enumerate(refs):
            if not ref.text.strip():
                raise RoutePolicyInputError(
                    f"{field_name} refs_with_text[{index}].text is required"
                )
            if not _has_source_location(ref):
                raise RoutePolicyInputError(
                    f"{field_name} refs_with_text[{index}] source location is required"
                )


def _has_source_location(ref: EvidenceTextRef) -> bool:
    return any(
        [
            bool(ref.document_id and ref.document_id.strip()),
            ref.page is not None,
            bool(ref.block_id and ref.block_id.strip()),
            bool(ref.span and ref.span.strip()),
        ]
    )
