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
        "You are the broad planning stage in a document extraction workflow. "
        "You will see the full HTML, the document tree, and the task_spec. "
        "Your only job is to produce an executable plan for the resolution agent, "
        "and you must only call return_broad_plan. return_broad_plan is a structured-output "
        "function, not a document-reading tool. "
        "You must not call any document-reading tools, must not extract final field values directly, "
        "and must not prefill answers. Do not prefill answers. "
        "The plan is a navigation plan, not an answer draft. "
        "Do not include concrete extracted values in the summary, plan, or risks. "
        "Do not write concrete extracted values or normalized field values. "
        "Use the field names and descriptions from task_spec as categories, without adding task-specific field semantics here. "
        "A plan may mention relevant section ids, element ids, table ids, section titles, table columns, "
        "and search/query strategies, but it must not contain final assignments such as field=value, "
        "field: value, or set field X to Y. "
        "The plan must be suitable for frontend replay: each plan item should be an action unit that "
        "can be marked with update_plan as in_progress/completed by the resolution agent. "
        "Prefer grouping by field or tightly related fields. Each plan item should explain where to read, "
        "which tool to use, and which field category should be written after the step. "
        "Do not split the plan into tiny fragments, and do not put the whole document into one large step. "
        "Write plan text in the same language as the document whenever possible. "
        "Tools available to the resolution agent are listed below for planning only. "
        "You must not call these tools in the broad stage: "
        "update_plan(plan_index, status, reason) synchronizes plan state; "
        "search_elements(query, reason, limit) searches text-like elements and returns candidate ids/snippets; "
        "read_element(element_id, reason) reads one element; for tables it returns only a table-ref and columns; "
        "read_section(section_id, reason, depth) reads a section; "
        "table_extraction(table_id, sql, reason) runs SELECT queries against the SQL table data; "
        "paragraph_extraction(element_id, pattern, reason) runs a regex over a text element; "
        "set_field(name, value, evidence_ids, reason, status, failure_reason) writes a field; "
        "finish() completes extraction. "
        "When planning table steps, first read_element(table_id) to inspect columns, then use table_extraction. "
        "Small tables may use SELECT *. Do not plan an unbounded SELECT * for large tables; "
        "select necessary columns and add WHERE conditions when possible. "
        "If the table structure is messy or no reliable WHERE condition is available, plan a bounded page read "
        "such as SELECT * FROM data LIMIT 50 OFFSET 0. "
        "The set_field reason should explain query_audit.summary. "
        "Do not turn blank filter columns directly into a risk conclusion; let resolution interpret them using "
        "field semantics, refs, and output-column emptiness. "
        "Example plan items: 'Read table p004_b002 and use table_extraction to extract enrollment-count fields'; "
        "'Read the <Japanese Criteria> eligibility section for the master program and extract eligibility fields'. "
    )
    user = "\n\n".join(
        [
            "任务规格 task_spec:\n" + _to_json(_read(state, "task_spec")),
            "文档树 document_tree:\n" + _to_json(_read(_read(state, "document"), "tree")),
            "完整 HTML 文档:\n" + _read(_read(state, "extraction_input"), "html", ""),
            (
                "Tools available to the resolution agent are for planning reference only. "
                "You must not call these tools in the broad stage; only call return_broad_plan. "
                "When planning, specify which tool and id the resolution agent should use, "
                "and which necessary columns a table query should select."
            ),
        ]
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def run_broad_planner(state: Any, broad_model: Any) -> BroadPlan:
    """Skip broad planning and let resolution work from the outline directly."""

    plan = BroadPlan(summary="No broad plan", plan=[], risks=[])
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
        plan = _string_list(args.get("plan", []))
        risks = _string_list(args.get("risks", []))
        return BroadPlan(summary=summary, plan=plan, risks=risks)
    raise ValueError("model did not call return_broad_plan")


def format_broad_plan(plan: BroadPlan) -> str:
    lines = [f"摘要: {plan.summary}", "计划:"]
    lines.extend(f"{index}. {step}" for index, step in enumerate(plan.plan, start=1))
    lines.append("风险:")
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


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return [stripped]
        return _string_list(parsed)
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


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
