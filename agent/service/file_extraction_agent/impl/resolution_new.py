"""Resolution agent loop for HTML extraction."""

from __future__ import annotations

from html import escape
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import MessagesState
from langgraph.prebuilt import ToolNode

from service.file_extraction_agent.impl.broad_new import format_broad_plan
from service.file_extraction_agent.impl.html_tools import build_tools


def build_resolution_messages(state: Any) -> list[Any]:
    system = SystemMessage(
        content=(
            "你是 HTML 文档抽取流程里的 resolution agent。你的输出会被前端做成“人类查找文档”的动画，"
            "所以每一次工具调用都必须像一个清晰、可信、可展示的动作。"
            "你不是聊天助手，也不是研究助手；你是字段写入 agent。目标是把 Task fields 里的每个字段写完。"
            "每个字段最终必须且只能调用一次 set_field，status 为 resolved 或 failed。"
            "一次只处理一个字段或 broad plan 中强相关的一组字段；不要一边浏览多个区域一边最后统一写字段。"
            "除 finish 外，每个工具调用都有必填 reason。reason 是展示给用户看的中文旁白，"
            "要短、具体、像人在解释自己为什么现在看这里；不要写内部术语、不要写泛泛的'继续抽取'。"
            "调用轨迹必须适合前端 replay："
            "1. 开始执行某条 broad plan 前，先调用 update_plan(plan_index, 'in_progress', reason)。"
            "只能推进最早一个未完成的 broad plan，不能跳过前面的 plan_index，"
            "也不能在前一项未 completed 时直接 update 后面的 plan。"
            "2. 然后只读取完成这条 plan 所需的证据。"
            "3. 一旦某个字段证据足够，下一次相关工具调用必须是 set_field，不要继续乱看。"
            "4. 与该 plan 相关的字段写入或失败决策完成后，立刻调用 update_plan(plan_index, 'completed', reason)，"
            "让右侧 plan 可以画线标记完成。没有 set_field 或明确失败决策前，不要 completed。"
            "5. 所有字段完成后再调用 finish。"
            "使用内置 document outline 选择 element id。优先先看目录/contents/index 相关页面来定位章节；"
            "除非当前字段需要文档标题，不要在封面和无关标题上游荡。"
            "如果候选是章节标题，优先使用 read_section，并使用最小够用 depth："
            "depth=1 看窄章节，depth=2 看相邻子章节，depth=3 只用于完整大章。"
            "如果同一字段已经在同一章节 read_element 了 3 次以上，停止零散 read_element，改用父章节 read_section 加大 depth。"
            "表格先 read_element(table_id) 看字段行，再 table_extraction 查询；SQL 里所有列名必须用双引号包住。"
            "table_extraction 会返回 query_audit.summary，它是查表事实，不是风险结论。"
            "写 set_field reason 时必须解释 query_audit.summary 对当前字段的影响，特别是筛选列空白、near_match_rows、输出列空值和结构错位观察。"
            "query_audit few-shot："
            "例 1：你查询 WHERE “类别列”='目标类别'，summary 显示筛选列有空白。"
            "如果表头、表注、分组标题或相邻列明确说明空白行属于非目标类别，且选中行输出列完整，"
            "set_field reason 可以说明这个表格上下文，并写 resolved。"
            "例 2：你查询 WHERE “类别列”='目标类别'，summary 显示筛选列有空白、near_match_rows 或输出列空值。"
            "如果空白行的相邻列、表注或表头不能证明它是非目标类别，不能只因为空白行未被 WHERE 选中就说正常；"
            "必须继续查表、改用更稳妥的查询，或 set_field(status='failed') 说明需要人工检查。"
            "空白筛选列必须结合表格上下文判断，不能把 query_audit.summary 直接改写成风险或正常结论。"
            "文本用 paragraph_extraction；普通 HTML 片段用 read_element/read_section。"
            "工具返回 ok=false 或 error 时，不要退出，读错误并修正参数重试。"
            "set_field 的 evidence_ids 必须来自本轮 read_element/read_section/table_extraction/paragraph_extraction 的结果，"
            "不能只凭 overview 或 broad plan 写字段。"
        )
    )
    human = HumanMessage(
        content="\n\n".join(
            [
                "Broad plan（右侧 plan 会根据 update_plan 动作逐项划线完成）:\n" + format_broad_plan(state.broad_plan),
                "Task fields（必须逐个 set_field）:\n" + _task_fields_text(state.task_spec),
                "Document outline（用于选择 read_section/read_element/table_extraction 的 id）:\n"
                + format_document_outline(state.document.tree),
            ]
        )
    )
    return [system, human]


def run_resolution(state: Any, resolution_model: Any) -> dict[str, Any]:
    tools = build_tools(state)
    messages = build_resolution_messages(state)

    if _supports_bind_tools(resolution_model):
        graph = build_resolution_graph(resolution_model, tools, state)
        output = graph.invoke({"messages": messages}, config={"recursion_limit": state.run_options.max_tool_calls * 2 + 10})
        finish_actions = [
            action for action in state.actions if action.get("tool_name") == "finish"
        ]
        if finish_actions:
            return finish_actions[-1]["result"]
        return {"ok": False, "errors": [{"message": "resolution did not call finish"}], "output": output}

    return _run_fake_model_loop(state, resolution_model)


def build_resolution_graph(resolution_model: Any, tools: list[Any], state: Any):
    model = resolution_model.bind_tools(tools)
    tool_node = ToolNode(tools)

    def call_model(graph_state: MessagesState):
        return {"messages": [model.invoke(graph_state["messages"])]}

    def nudge_model(graph_state: MessagesState):
        return {"messages": [HumanMessage(content=_continue_instruction(state))]}

    def should_continue(graph_state: MessagesState):
        if len(state.actions) >= state.run_options.max_tool_calls:
            return END
        if _has_successful_finish(state):
            return END
        messages = graph_state["messages"]
        last_message = messages[-1]
        if getattr(last_message, "tool_calls", None):
            return "tools"
        if _should_force_set_field_nudge(state):
            return "nudge"
        if not _has_successful_finish(state) and _should_nudge_resolution(state):
            return "nudge"
        return END

    graph = StateGraph(MessagesState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", tool_node)
    graph.add_node("nudge", nudge_model)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", "nudge": "nudge", END: END})
    graph.add_edge("tools", "agent")
    graph.add_edge("nudge", "agent")
    return graph.compile()


def _run_fake_model_loop(state: Any, model: Any) -> dict[str, Any]:
    """Small deterministic loop for unit tests using models that emit tool calls."""

    tools = {getattr(tool, "name", getattr(tool, "__name__", "")): tool for tool in build_tools(state)}
    messages = build_resolution_messages(state)
    for _ in range(state.run_options.max_tool_calls):
        call = model.invoke(messages)
        name = _read(call, "tool_name") or _read(call, "name")
        args = _read(call, "arguments", {}) or _read(call, "args", {}) or {}
        tool = tools.get(name)
        if tool is None:
            return {"ok": False, "errors": [{"message": f"unknown tool: {name}"}]}
        result = tool.invoke(args) if hasattr(tool, "invoke") else tool(**args)
        messages.append({"tool": name, "result": result})
        if name == "finish":
            return result
    return {"ok": False, "errors": [{"message": "max_tool_calls exceeded"}]}


def _supports_bind_tools(model: Any) -> bool:
    return callable(getattr(model, "bind_tools", None))


def _has_successful_finish(state: Any) -> bool:
    return any(
        action.get("tool_name") == "finish" and (action.get("result") or {}).get("ok") is True
        for action in getattr(state, "actions", []) or []
    )


def _has_unfinished_fields(state: Any) -> bool:
    field_states = getattr(state, "field_states", {}) or {}
    return any(field.name not in field_states for field in getattr(state.task_spec, "fields", []) or [])


def _should_nudge_resolution(state: Any) -> bool:
    return bool(getattr(state.task_spec, "fields", []) or [])


def _continue_instruction(state: Any) -> str:
    field_states = getattr(state, "field_states", {}) or {}
    if _should_force_set_field_nudge(state):
        return (
            "你已经读取了多个证据但还没有写字段。停止继续浏览。"
            "如果当前字段证据已经足够，下一次工具调用必须是 set_field。"
            "如果证据还不够，只能再做一次针对同一字段的精确工具调用，然后 set_field。"
            "不要切换到别的字段。相关 plan 完成后调用 update_plan，status=completed。"
            "继续时只能推进最早未完成的 broad plan，不要跳到后面的 plan_index。"
            "不要用普通文本回答。"
        )
    missing = [
        field.name
        for field in getattr(state.task_spec, "fields", []) or []
        if field.name not in field_states
    ]
    if missing:
        return (
            "抽取还没有完成。缺失字段: "
            + ", ".join(missing)
            + "。继续使用工具。每个缺失字段只读取必要证据，证据足够后立刻 set_field，"
            "然后再处理下一个字段。开始和完成相关 broad plan 时都要调用 update_plan。"
            "update_plan 只能按最早未完成的 broad plan 顺序推进，不能跳过前面的 plan_index。"
            "不要先收集多个字段的证据再统一写入。不要用普通文本回答。"
        )
    return (
        "所有字段都已经 set_field，但 finish 还没有成功。现在调用 finish。"
        "如果 finish 返回错误，用 set_field 修正后再次调用 finish。不要用普通文本回答。"
    )


def _task_fields_text(task_spec: Any) -> str:
    lines = []
    for field in getattr(task_spec, "fields", []) or []:
        lines.append(
            f"- {field.name}: type={field.type}, required={field.required}, description={field.description or ''}"
        )
    if getattr(task_spec, "instructions", None):
        lines.append("Instructions: " + task_spec.instructions)
    return "\n".join(lines)


def format_document_outline(tree: list[dict[str, Any]]) -> str:
    lines: list[str] = ["<outline>"]
    index_nodes = select_index_outline_nodes(tree)
    if index_nodes:
        lines.append('  <index-pages purpose="use these first to locate sections">')
        _append_outline_lines(index_nodes, lines, depth=2, section_stack=[])
        lines.append("  </index-pages>")
        lines.append('  <main-outline purpose="use after choosing candidate sections from index pages">')
        _append_outline_lines(tree, lines, depth=2, section_stack=[], skip_ids={node.get("id", "") for node in index_nodes})
        lines.append("  </main-outline>")
    else:
        _append_outline_lines(tree, lines, depth=1, section_stack=[])
    lines.append("</outline>")
    return "\n".join(lines)


def select_index_outline_nodes(tree: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return likely table-of-contents/index nodes for the model to consult first."""

    selected: list[dict[str, Any]] = []
    for node in tree:
        text = str(node.get("text") or node.get("label") or "")
        normalized = text.replace(" ", "").lower()
        if (
            "目次" in normalized
            or "contents" in normalized
            or "tableofcontents" in normalized
            or "index" == normalized
        ):
            selected.append(node)
    return selected[:2]


def _append_outline_lines(
    nodes: list[dict[str, Any]],
    lines: list[str],
    depth: int,
    section_stack: list[str],
    skip_ids: set[str] | None = None,
) -> None:
    for node in nodes:
        if skip_ids and node.get("id", "") in skip_ids:
            continue
        indent = "  " * depth
        node_id = node.get("id", "")
        node_type = node.get("type", "")
        if node_type == "TABLE":
            columns = " | ".join(str(column) for column in node.get("columns", []) or [])
            row_count = node.get("row_count", 0)
            label = node.get("label") or (section_stack[-1] if section_stack else "")
            label_attr = f' label="{_attr(label)}"' if label else ""
            lines.append(
                f'{indent}<table-ref id="{_attr(node_id)}"{label_attr} rows="{_attr(row_count)}" columns="{_attr(columns)}" />'
            )
            continue

        if node_type in {"TITLE", "SECTION_HEADER"}:
            text = str(node.get("text", ""))
            level = _heading_level(node_type, depth)
            lines.append(
                f'{indent}<section id="{_attr(node_id)}" level="{_attr(level)}" title="{_attr(text)}">'
            )
            _append_outline_lines(
                node.get("children", []) or [],
                lines,
                depth + 1,
                [*section_stack, text],
                skip_ids=skip_ids,
            )
            lines.append(f"{indent}</section>")
        else:
            _append_outline_lines(
                node.get("children", []) or [],
                lines,
                depth,
                section_stack,
                skip_ids=skip_ids,
            )


def _should_force_set_field_nudge(state: Any) -> bool:
    actions = getattr(state, "actions", []) or []
    if len(actions) < 4:
        return False
    recent = actions[-4:]
    if any(action.get("tool_name") == "set_field" for action in recent):
        return False
    read_like = {"read_element", "read_section", "table_extraction", "paragraph_extraction"}
    return sum(1 for action in recent if action.get("tool_name") in read_like) >= 4


def _heading_level(node_type: str, depth: int) -> int:
    if node_type == "TITLE":
        return 1
    return max(1, depth)


def _attr(value: Any) -> str:
    return escape(str(value), quote=True)


def _read(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


__all__ = [
    "build_resolution_messages",
    "build_resolution_graph",
    "format_document_outline",
    "run_resolution",
]
