"""把 route policy 业务结果适配成 HTTP 出口。"""

from __future__ import annotations

from importlib import import_module
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from service.route_policy_agent.policy_client import (
    RoutePolicyClientConfigError,
    RoutePolicyClientInvocationError,
)
from service.route_policy_agent.schemas import (
    FieldRefsWithText,
    PolicyOptions,
    RouteFieldProcess,
    RouteFieldOutput,
    RoutePolicyResult,
    TaskSpec,
)


StructuredOutputStrategy = Literal["tool_call"]

router = APIRouter(tags=["route-policy-agent"])


class EvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_spec: TaskSpec
    field_outputs: list[RouteFieldOutput]
    refs_with_text: list[FieldRefsWithText]
    field_processes: list[RouteFieldProcess]
    policy_options: PolicyOptions | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    base_url: str | None = None
    openai_api_key: str | None = None
    model: str | None = None
    structured_output_strategy: StructuredOutputStrategy = "tool_call"


@router.post("/v1/route-policy-agent/evaluate", response_model=RoutePolicyResult)
async def evaluate_route_policy(request: EvaluateRequest) -> RoutePolicyResult:
    try:
        return await run_in_threadpool(_evaluate_route_policy, request)
    except (ValueError, RoutePolicyClientConfigError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except RoutePolicyClientInvocationError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


def _evaluate_route_policy(request: EvaluateRequest) -> RoutePolicyResult:
    evaluate = import_module("service.route_policy_agent.processor").evaluate
    return evaluate(
        task_spec=request.task_spec,
        field_outputs=request.field_outputs,
        refs_with_text=request.refs_with_text,
        field_processes=request.field_processes,
        policy_options=request.policy_options,
        metadata=request.metadata,
        base_url=request.base_url,
        openai_api_key=request.openai_api_key,
        model=request.model,
        structured_output_strategy=request.structured_output_strategy,
    )
