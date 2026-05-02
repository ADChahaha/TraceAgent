"""Broad planner for the HTML extraction flow."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any

try:
    from langchain_core.tools import tool
except Exception:  # pragma: no cover
    def tool(function=None, *args: Any, **kwargs: Any):  # type: ignore[no-redef]
        if function is None:
            return lambda wrapped: wrapped
        return function


@dataclass
class BroadPlan:
    summary: str
    plan: list[str]
    risks: list[str]


@tool
def return_broad_plan(summary: str, plan: list[str], risks: list[str]) -> dict[str, Any]:
    """
    Return the broad extraction plan for the resolution agent.

    This is only a structured-output function for the broad stage. It is not a
    document extraction tool and it must not contain final field values.

    Args:
        summary: Short document-level summary.
        plan: Ordered execution steps for the resolution agent.
        risks: Important ambiguities or extraction risks.
    """

    return {"summary": summary, "plan": plan, "risks": risks}


def build_broad_messages(state: Any) -> list[dict[str, str]]:
    """Build planner messages from task fields, overview tree, and full HTML."""

    system = (
        "You are the broad planning stage for a document extraction workflow. "
        "Create a concise plan for the resolution agent after reading the full "
        "HTML document. Do not extract final field values, do not call document "
        "tools, and do not invent evidence ids. "
        "Return only the plan by calling return_broad_plan. return_broad_plan is "
        "a structured-output function, not a document tool."
    )
    user = "\n\n".join(
        [
            "Task spec:\n" + _to_json(_read(state, "task_spec")),
            "Document tree:\n" + _to_json(_read(_read(state, "document"), "tree")),
            "Full HTML document:\n" + _read(_read(state, "extraction_input"), "html", ""),
            (
                "Resolution agent capabilities, for planning context only: it can "
                "inspect the overview, read one element by id, query one table with "
                "SQL, search one text element with regex, set fields, and finish "
                "after validation. These capabilities are not available to broad; "
                "broad must only return a plan."
            ),
        ]
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def run_broad_planner(state: Any, broad_model: Any) -> BroadPlan:
    """Run broad planner with a required function-call output tool."""

    messages = build_broad_messages(state)
    model = broad_model.bind_tools([return_broad_plan], tool_choice="return_broad_plan")
    message = model.invoke(messages)
    plan = parse_broad_plan_tool_call(message)
    setattr(state, "broad_plan", plan)
    return plan


def parse_broad_plan_tool_call(message: Any) -> BroadPlan:
    """Parse a return_broad_plan tool call from a model message."""

    for call in _read(message, "tool_calls", []) or []:
        name = _read(call, "name") or _read(_read(call, "function", {}), "name")
        if name != "return_broad_plan":
            continue
        args = _read(call, "args", None)
        if args is None:
            raw_args = _read(_read(call, "function", {}), "arguments", "{}")
            args = json.loads(raw_args)
        summary = str(args.get("summary", ""))
        plan = [str(item) for item in args.get("plan", [])]
        risks = [str(item) for item in args.get("risks", [])]
        return BroadPlan(summary=summary, plan=plan, risks=risks)
    raise ValueError("model did not call return_broad_plan")


def format_broad_plan(plan: BroadPlan) -> str:
    lines = [f"Summary: {plan.summary}", "Plan:"]
    lines.extend(f"{index}. {step}" for index, step in enumerate(plan.plan, start=1))
    lines.append("Risks:")
    lines.extend(f"- {risk}" for risk in plan.risks)
    return "\n".join(lines)


def _to_json(value: Any) -> str:
    return json.dumps(_plain(value), ensure_ascii=False, indent=2)


def _plain(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if hasattr(value, "__dict__"):
        return {key: _plain(item) for key, item in vars(value).items()}
    return value


def _read(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


__all__ = [
    "BroadPlan",
    "return_broad_plan",
    "build_broad_messages",
    "run_broad_planner",
    "parse_broad_plan_tool_call",
    "format_broad_plan",
]
