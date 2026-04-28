"""把已校验输入合并为单字段 route 判断上下文。"""

from __future__ import annotations

from dataclasses import dataclass

from service.file_extraction_agent.schemas import FieldDefinition
from service.route_policy_agent.input_validator import ValidatedPolicyInput
from service.route_policy_agent.schemas import EvidenceTextRef, RouteFieldOutput


@dataclass(frozen=True, slots=True)
class FieldPolicyContext:
    """单字段 route 判断所需的最小上下文。"""

    field_definition: FieldDefinition
    field_output: RouteFieldOutput
    refs_with_text: list[EvidenceTextRef]


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
            )
        )
    return contexts
