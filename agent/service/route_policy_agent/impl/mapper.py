"""把已校验输入合并为单字段 route 判断上下文。"""

from __future__ import annotations

from dataclasses import dataclass

from service.file_extraction_agent.schemas import FieldDefinition
from service.route_policy_agent.input_validator import ValidatedPolicyInput
from service.route_policy_agent.schemas import (
    EvidenceTextRef,
    RouteFieldOutput,
    RouteFieldProcess,
)


@dataclass(frozen=True, slots=True)
class FieldPolicyContext:
    """单字段 route 判断所需的最小上下文。"""

    field_definition: FieldDefinition
    field_output: RouteFieldOutput
    refs_with_text: list[EvidenceTextRef]
    field_process: RouteFieldProcess
    related_field_processes: list[RouteFieldProcess]


def build_field_policy_contexts(
    validated_input: ValidatedPolicyInput,
) -> list[FieldPolicyContext]:
    """按 field_outputs 顺序合并字段定义、字段输出和 refs 文本。"""

    contexts: list[FieldPolicyContext] = []
    for field_output in validated_input.route_input.field_outputs:
        field_name = field_output.field_name
        contexts.append(
            FieldPolicyContext(
                field_definition=validated_input.field_definitions_by_name[field_name],
                field_output=validated_input.field_outputs_by_name[field_name],
                refs_with_text=validated_input.refs_by_field_name[field_name],
                field_process=validated_input.processes_by_field_name[field_name],
                related_field_processes=_related_field_processes(
                    field_definition=validated_input.field_definitions_by_name[field_name],
                    processes_by_field_name=validated_input.processes_by_field_name,
                    current_field_name=field_name,
                ),
            )
        )
    return contexts


def _related_field_processes(
    *,
    field_definition: FieldDefinition,
    processes_by_field_name: dict[str, RouteFieldProcess],
    current_field_name: str,
) -> list[RouteFieldProcess]:
    related_names = _related_field_names(field_definition)
    return [
        processes_by_field_name[field_name]
        for field_name in related_names
        if field_name != current_field_name and field_name in processes_by_field_name
    ]


def _related_field_names(field_definition: FieldDefinition) -> list[str]:
    validation_rules = field_definition.validation_rules or {}
    names: list[str] = []
    source_field = validation_rules.get("source_field")
    if isinstance(source_field, str) and source_field:
        names.append(source_field)
    source_fields = validation_rules.get("source_fields")
    if isinstance(source_fields, list):
        names.extend(
            item
            for item in source_fields
            if isinstance(item, str) and item
        )
    return list(dict.fromkeys(names))
