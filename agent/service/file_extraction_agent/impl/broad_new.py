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
        "你是文档抽取流程里的 broad planning 阶段。你会看到完整 HTML、文档树和 task_spec。"
        "你的唯一任务是为 resolution agent 生成一个可执行计划，并且必须只调用 "
        "return_broad_plan 返回计划。return_broad_plan 是结构化输出函数，不是文档工具。"
        "你不能调用任何读文档工具，不能直接抽取最终字段值，不能预先填答案。"
        "计划可以写相关 section id、element id、table id、章节标题、表格列名、检索策略，"
        "但不要写 field=value、field: value、set field X to Y 这类最终赋值。"
        "计划要适合前端 replay 展示：每一条 plan 应该是一个可以被 resolution agent "
        "用 update_plan 标记 in_progress/completed 的动作单元。"
        "优先按字段或强相关字段分组，每条计划要说明应该读哪里、用什么工具、完成后应写入什么字段类别。"
        "不要把计划拆得过碎，也不要把整份文档塞进一个大步骤。"
        "Resolution 后续可用工具如下，你必须据此写计划，但你现在不能调用这些工具："
        "update_plan(plan_index, status, reason) 用于同步 plan 状态；"
        "read_element(element_id, reason) 读取单个元素，表格只返回 table-ref 和列名；"
        "read_section(section_id, reason, depth) 读取章节；"
        "table_extraction(table_id, sql, reason) 对 SQL 表 data 做 SELECT 查询；"
        "paragraph_extraction(element_id, pattern, reason) 对文本元素做正则匹配；"
        "set_field(name, value, evidence_ids, reason, status, failure_reason) 写字段；"
        "finish() 结束抽取。"
        "规划表格步骤时，必须先 read_element(table_id) 看列名，再 table_extraction。"
        "小表可以 SELECT *；大表不要规划裸 SELECT *，要规划选择必要列并尽量加 WHERE 条件。"
        "如果表格结构混乱、无法可靠 WHERE，保底规划 SELECT * FROM data LIMIT 50 OFFSET 0 "
        "这种 50 行以内的分页读取。"
        "示例写法：'读取 p004_b002 表格，用 table_extraction 提取募集人数相关字段'；"
        "'阅读 <日本語基準> 博士課程前期課程 的出願資格章节，提取申请资格字段'。"
    )
    user = "\n\n".join(
        [
            "任务规格 task_spec:\n" + _to_json(_read(state, "task_spec")),
            "文档树 document_tree:\n" + _to_json(_read(_read(state, "document"), "tree")),
            "完整 HTML 文档:\n" + _read(_read(state, "extraction_input"), "html", ""),
            (
                "Resolution 后续可用工具仅供你规划参考；你现在不能调用这些工具，"
                "只能 return_broad_plan。规划时要写出 resolution 应该用哪个 tool、哪个 id、"
                "以及表格查询应选择哪些必要列。"
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
