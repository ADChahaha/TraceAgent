"""route_policy_agent 对外统一入口。

实现步骤：

```text
调用方传入 task_spec、field_outputs、refs_with_text 和 field_processes
  -> RoutePolicyInput 解析，只保留 route 判断需要的输入
  -> input_validator 校验字段名、字段输出、refs 文本和过程摘要完整性
  -> mapper 按 field_name 合并字段定义、字段输出、refs 文本和两阶段过程摘要
  -> failed 且 critical/required 的字段直接 reject
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
from service.route_policy_agent.input_validator import validate_route_policy_input
from service.route_policy_agent.policy_client import build_policy_client
from service.route_policy_agent.schemas import (
    FieldRefsWithText,
    FieldRouteDecision,
    PolicyOptions,
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
    policy_options: PolicyOptions | dict[str, Any] | None = None,
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
        policy_options=policy_options or PolicyOptions(),
        metadata=metadata or {},
    )
    validated_input = validate_route_policy_input(route_input)
    contexts = build_field_policy_contexts(validated_input)

    resolved_client = policy_client
    field_routes: list[FieldRouteDecision] = []
    for context in contexts:
        if context.field_output.status == "failed":
            field_routes.append(_route_failed_field(context))
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
            messages=build_route_policy_messages(
                context=context,
                policy_options=route_input.policy_options,
            ),
        )
        field_routes.append(
            FieldRouteDecision(
                field_name=context.field_output.field_name,
                route=decision.route,
                route_reason=decision.route_reason,
            )
        )

    return RoutePolicyResult(
        field_routes=field_routes,
        metadata=dict(route_input.metadata),
    )


def _route_failed_field(context: FieldPolicyContext) -> FieldRouteDecision:
    field = context.field_definition
    if field.critical or (field.required and not field.allow_missing):
        flags = _field_blocking_flags(context)
        return FieldRouteDecision(
            field_name=context.field_output.field_name,
            route="reject",
            route_reason=(
                f"字段 {field.field_name} 抽取失败，且属于 {flags} 字段，"
                "不允许自动进入提交。"
            ),
        )

    return FieldRouteDecision(
        field_name=context.field_output.field_name,
        route="review",
        route_reason=(
            f"字段 {field.field_name} 抽取失败，但不是阻断字段，"
            "需要人工检查后决定是否补录。"
        ),
    )


def _field_blocking_flags(context: FieldPolicyContext) -> str:
    field = context.field_definition
    flags: list[str] = []
    if field.critical:
        flags.append("critical")
    if field.required and not field.allow_missing:
        flags.append("required")
    return " / ".join(flags)
