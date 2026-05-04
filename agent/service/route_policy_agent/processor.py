"""route_policy_agent 对外统一入口。

实现步骤：

```text
调用方传入 task_spec、field_outputs、refs_with_text 和 field_processes
  -> RoutePolicyInput 解析，只保留 route 判断需要的输入
  -> input_validator 校验字段名、字段输出、refs 文本和过程摘要完整性
  -> mapper 按 field_name 合并字段定义、字段输出、refs 文本和两阶段过程摘要
  -> required 且不允许缺失的字段如果没填，直接 review
  -> resolved 字段构造单字段 route prompt，并调用 policy_client 输出 RoutePolicyDecision
  -> 汇总成 RoutePolicyResult(field_routes[])
```
"""

from __future__ import annotations

from typing import Any, Literal

from service.file_extraction_agent.schemas import TaskSpec
from service.route_policy_agent.impl.mapper import FieldPolicyContext
from service.route_policy_agent.impl.mapper import build_field_policy_contexts
from service.route_policy_agent.impl.prompts import build_route_policy_messages
from service.route_policy_agent.input_validator import (
    ValidatedPolicyInput,
    validate_route_policy_input,
)
from service.route_policy_agent.policy_client import build_policy_client
from service.route_policy_agent.schemas import (
    FieldRefsWithText,
    FieldRouteDecision,
    RouteFieldProcess,
    RouteFieldOutput,
    RoutePolicyDecision,
    RoutePolicyInput,
    RoutePolicyResult,
)


StructuredOutputStrategy = Literal["tool_call"]


def evaluate(
    *,
    task_spec: TaskSpec | dict[str, Any],
    field_outputs: list[RouteFieldOutput | dict[str, Any]],
    refs_with_text: list[FieldRefsWithText | dict[str, Any]],
    field_processes: list[RouteFieldProcess | dict[str, Any]],
    metadata: dict[str, Any] | None = None,
    base_url: str | None = None,
    openai_api_key: str | None = None,
    model: str | None = None,
    structured_output_strategy: StructuredOutputStrategy = "tool_call",
    policy_client: Any | None = None,
) -> RoutePolicyResult:
    """消费外部已校验主输入，执行字段级 route policy 判断。"""

    route_input = RoutePolicyInput(
        task_spec=task_spec,
        field_outputs=field_outputs,
        refs_with_text=refs_with_text,
        field_processes=field_processes,
        metadata=metadata or {},
    )
    validated_input = validate_route_policy_input(route_input)
    contexts = build_field_policy_contexts(validated_input)

    resolved_client = policy_client
    field_routes: list[FieldRouteDecision] = []
    for context in contexts:
        missing_route = _route_missing_required_field(context)
        if missing_route is not None:
            field_routes.append(missing_route)
            continue

        missing_process_route = _route_missing_extraction_process(context)
        if missing_process_route is not None:
            field_routes.append(missing_process_route)
            continue

        if resolved_client is None:
            resolved_client = build_policy_client(
                base_url=base_url,
                api_key=openai_api_key,
                model=model,
                structured_output_strategy=structured_output_strategy,
            )

        decision = resolved_client.invoke(
            output_schema=RoutePolicyDecision,
            messages=build_route_policy_messages(context=context),
        )
        field_routes.append(
            FieldRouteDecision(
                field_name=context.field_output.field_name,
                route=decision.route,
                route_reason=decision.route_reason,
            )
        )

    field_routes.extend(_route_missing_required_outputs(validated_input))

    return RoutePolicyResult(
        field_routes=field_routes,
        metadata=dict(route_input.metadata),
    )


def _route_missing_required_field(
    context: FieldPolicyContext,
) -> FieldRouteDecision | None:
    field = context.field_definition
    if not _is_required_without_missing_allowed(field):
        if context.field_output.status == "failed":
            return FieldRouteDecision(
                field_name=context.field_output.field_name,
                route="review",
                route_reason=(
                    f"字段 {field.field_name} 抽取失败，但不是阻断字段，"
                    "需要人工检查后决定是否补录。"
                ),
            )
        return None

    if context.field_output.status == "failed":
        return FieldRouteDecision(
            field_name=context.field_output.field_name,
            route="review",
            route_reason=(
                f"字段 {field.field_name} 是 required 字段，"
                "抽取失败导致字段没有填，需要人工复核或补录。"
            ),
        )

    if _is_empty_value(context.field_output.value):
        return FieldRouteDecision(
            field_name=context.field_output.field_name,
            route="review",
            route_reason=(
                f"字段 {field.field_name} 是 required 字段，"
                "但字段值为空，需要人工复核或补录。"
            ),
        )

    return None


def _route_missing_extraction_process(
    context: FieldPolicyContext,
) -> FieldRouteDecision | None:
    if context.field_output.status != "resolved":
        return None
    process = context.field_process
    has_broad_signal = bool(
        process.broad_extraction.search_queries
        or process.broad_extraction.candidate_action_count > 0
        or process.broad_extraction.finish_reason
    )
    has_resolution_signal = bool(
        process.field_resolution.search_queries
        or process.field_resolution.candidate_action_count > 0
        or process.field_resolution.final_decision_used
        or process.field_resolution.reason
    )
    if has_broad_signal or has_resolution_signal:
        return None
    return FieldRouteDecision(
        field_name=context.field_output.field_name,
        route="review",
        route_reason=(
            f"字段 {context.field_output.field_name} 已返回 resolved，"
            "但抽取过程摘要为空：没有 search 查询、候选写入、broad 结束原因或最终定案记录。"
            "即使 refs 文本存在，也需要人工复核抽取路径是否遗漏内容。"
        ),
    )


def _route_missing_required_outputs(
    validated_input: ValidatedPolicyInput,
) -> list[FieldRouteDecision]:
    missing_routes: list[FieldRouteDecision] = []
    output_names = set(validated_input.field_outputs_by_name)
    for field in validated_input.route_input.task_spec.fields:
        if field.field_name in output_names:
            continue
        if not _is_required_without_missing_allowed(field):
            continue
        missing_routes.append(
            FieldRouteDecision(
                field_name=field.field_name,
                route="review",
                route_reason=(
                    f"字段 {field.field_name} 是 required 字段，"
                    "但 file_extraction_agent 没有返回该字段，需要人工复核或补录。"
                ),
            )
        )
    return missing_routes


def _is_required_without_missing_allowed(field: Any) -> bool:
    return bool(field.required and not field.allow_missing)


def _is_empty_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False
