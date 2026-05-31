"""Model-facing tools for document QA over a virtual HTML tree."""

from __future__ import annotations

import re
from typing import Any, Callable

try:
    from langchain_core.tools import tool
except Exception:  # pragma: no cover
    def tool(function=None, *args: Any, **kwargs: Any):  # type: ignore[no-redef]
        if function is None:
            return lambda wrapped: wrapped
        return function


EVIDENCE_LOCATOR_RE = re.compile(r"^evidence://(?P<path_id>\d{4}(?:\.\d{4})*)(?:/(?P<selector>[SIR]\d{3}(?:\.\d{3})*))?$")
RANGE_LOCATOR_RE = re.compile(r"^evidence://range/(?P<start>\d{4}(?:\.\d{4})*)/(?P<end>\d{4}(?:\.\d{4})*)$")
INLINE_SELECTOR_KEYS = {"S": "sentences", "I": "items", "R": "rows"}


def build_tools(state: Any) -> list[Any]:
    """Build model-facing QA navigation tools bound to the current graph state."""

    @tool
    def ls(path_id: str = "") -> dict[str, Any]:
        """List one level of the virtual document repository at a directory evidence link.

        Use this to see document structure. Leave path_id empty for the root.
        path_id MUST be a full evidence link starting with "evidence://" — e.g.
        evidence://0001 or evidence://0001.0003. Never pass a bare number like
        "0001" or "0001.0003" without the evidence:// prefix.
        Directory names show a trailing slash in ls output.
        ls returns only direct child directories and readable block links
        (.md/.list/.table); it does NOT recursively expand descendants and does
        NOT return file text. To get content, call read on a child block link.
        Start every investigation here to understand document layout before reading.
        """

        return _ls(state, path_id)

    @tool
    def grep(query: str, scope: str = "", kind: str = "", max_results: int = 20) -> dict[str, Any]:
        """Full-text search across readable blocks. Returns candidate locators with previews.

        Use for targeted lookups: dates, names, amounts, specific terms.
        Results are candidates only — NOT final evidence. Always read or inspect
        a candidate before citing it in your answer.
        scope: optional evidence link to limit search to a section.
        kind: optional filter — "paragraph", "list", or "table".
        max_results: default 20, max 50.
        """

        return _grep(state, query=query, scope=scope, kind=kind, max_results=max_results)

    @tool
    def read(locator: str) -> dict[str, Any]:
        """Read one block or a consecutive range of sibling blocks.

        locator MUST start with "evidence://" — never pass a bare path ID.
        Single block: pass evidence://0001.0001.0002 from ls output.
        Range of siblings: pass evidence://range/<start>/<end>, e.g.
        evidence://range/0001.0001.0002/0001.0001.0005 reads blocks 0002–0005
        together. Endpoints must be different readable siblings in the same
        section; the range must not cross a subsection boundary.
        Paragraphs return plain text. Lists return Markdown with Ixxx item ids.
        Tables return Markdown with Rxxx row ids.
        After reading, narrate what the block contains with actual values — then
        move on or cite it in your answer with an evidence link.
        """

        return _read(state, locator)

    @tool
    def inspect(locator: str) -> dict[str, Any]:
        """Expand one readable block into inline sentence/item/row evidence selectors.

        locator MUST start with "evidence://" — never pass a bare path ID.
        Use when you need to cite a specific fact within a block.
        Returns inline links: evidence://path_id/S001 (sentence), /I001 (list item),
        /R001 (table row), along with evidence_texts showing the text of each.
        Use these inline links in your final answer for precise citations.
        Only call inspect on blocks you have already read and need fine-grained
        evidence from. Not every block needs inspection.
        """

        return _inspect(state, locator)

    return [ls, grep, read, inspect]


def _ls(state: Any, path_id: str = "") -> dict[str, Any]:
    canonical_path_id = _directory_path_id_from_locator(path_id)
    return _run_tool(
        state,
        "ls",
        {"path_id": path_id},
        lambda: _locator_error(path_id, canonical_path_id) or _ls_result(state, canonical_path_id),
    )


def _grep(
    state: Any,
    *,
    query: str,
    scope: str = "",
    kind: str = "",
    max_results: int = 20,
) -> dict[str, Any]:
    def execute() -> dict[str, Any]:
        if not isinstance(query, str) or not query.strip():
            return {"ok": False, "errors": [{"code": "BAD_QUERY", "message": "query is required"}]}
        if kind and kind not in {"paragraph", "list", "table"}:
            return {"ok": False, "errors": [{"code": "BAD_KIND", "message": "kind must be paragraph, list, or table"}]}
        scope_path_id = _directory_path_id_from_locator(scope)
        if _locator_error(scope, scope_path_id):
            return _locator_error(scope, scope_path_id)  # type: ignore[return-value]
        results = _grep_results(
            state,
            query=query.strip(),
            scope_path_id=scope_path_id,
            kind=kind,
            max_results=max_results,
        )
        return {
            "ok": True,
            "query": query,
            "scope": _block_link(scope_path_id) if scope_path_id and scope_path_id != "0000" else "",
            "kind": kind,
            "results": results,
        }

    return _run_tool(
        state,
        "grep",
        {"query": query, "scope": scope, "kind": kind, "max_results": max_results},
        execute,
    )


def _read(state: Any, locator: str) -> dict[str, Any]:
    range_path_ids = _range_path_ids_from_locator(locator)
    if range_path_ids is not None:
        start_path_id, end_path_id = range_path_ids
        return _run_tool(
            state,
            "read",
            {"locator": locator},
            lambda: {"ok": True, **state.document.read_range(start_path_id, end_path_id)},
        )
    canonical_path_id = _block_path_id_from_locator(locator)
    return _run_tool(
        state,
        "read",
        {"locator": locator},
        lambda: _locator_error(locator, canonical_path_id)
        or {"ok": True, **_expose_read_result(state.document.read_markdown(canonical_path_id))},
    )


def _inspect(state: Any, locator: str) -> dict[str, Any]:
    canonical_path_id = _block_path_id_from_locator(locator)

    def execute() -> dict[str, Any]:
        locator_error = _locator_error(locator, canonical_path_id)
        if locator_error:
            return locator_error
        try:
            selector = state.document.inline_selector_for_path(canonical_path_id)
        except ValueError:
            return {
                "ok": False,
                "errors": [
                    {
                        "code": "UNREADABLE_INSPECT_PATH",
                        "message": "inspect requires a readable paragraph/list/table block evidence link",
                    }
                ],
            }
        evidence_texts = state.document.evidence_texts([selector])
        return {
            "ok": True,
            "locator": _block_link(selector["path_id"]),
            "evidence": _inline_links([selector]),
            "evidence_texts": _evidence_texts_for_tool(evidence_texts),
        }

    return _run_tool(state, "inspect", {"locator": locator}, execute)


def _ls_result(state: Any, path_id: str) -> dict[str, Any]:
    canonical_path_id = state.document.path_id(path_id)
    return {
        "ok": True,
        "locator": _block_link(canonical_path_id),
        "text": _link_locator_text(state.document.tree_text(canonical_path_id, depth=1)),
    }


def model_ls_text(document: Any, path: str = "/") -> str:
    return _link_locator_text(document.tree_text(path, depth=1))


def _grep_results(
    state: Any,
    *,
    query: str,
    scope_path_id: str | None,
    kind: str,
    max_results: int,
) -> list[dict[str, Any]]:
    query_lower = query.lower()
    bounded_limit = max(1, min(int(max_results or 20), 50))
    results: list[dict[str, Any]] = []
    for path_id, node in state.document.nodes_by_path_id.items():
        if node.kind not in {"paragraph", "list", "table"}:
            continue
        if kind and node.kind != kind:
            continue
        if scope_path_id and scope_path_id != "0000" and not _is_within_scope(path_id, scope_path_id):
            continue
        text = _node_search_text(state, path_id)
        if query_lower not in text.lower():
            continue
        results.append(
            {
                "locator": _block_link(path_id),
                "kind": node.kind,
                "document": node.source_document or "",
                "section": _section_label(node),
                "preview": _preview_around(text, query),
                "match_spans": [query],
            }
        )
        if len(results) >= bounded_limit:
            break
    return results


def _node_search_text(state: Any, path_id: str) -> str:
    result = state.document.read_markdown(path_id)
    text = result.get("text")
    return text if isinstance(text, str) else ""


def _is_within_scope(path_id: str, scope_path_id: str) -> bool:
    return path_id == scope_path_id or path_id.startswith(scope_path_id + ".")


def _section_label(node: Any) -> str:
    parent = getattr(node, "parent", None)
    if parent is not None:
        return getattr(parent, "display_name", None) or getattr(parent, "title", None) or getattr(parent, "name", "")
    return ""


def _preview_around(text: str, query: str, *, radius: int = 80) -> str:
    lower = text.lower()
    index = lower.find(query.lower())
    if index < 0:
        return text[: radius * 2]
    start = max(0, index - radius)
    end = min(len(text), index + len(query) + radius)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return prefix + text[start:end] + suffix


def _locator_error(locator: Any, canonical_path_id: str | None) -> dict[str, Any] | None:
    if isinstance(locator, str) and canonical_path_id:
        return None
    return {
        "ok": False,
        "errors": [
            {
                "code": "BAD_LOCATOR",
                "message": "use an evidence link like evidence://0001 copied from ls output",
            }
        ],
    }


def _block_path_id_from_locator(locator: Any) -> str | None:
    parsed = _parse_evidence_locator(locator)
    if parsed is None:
        return None
    path_id, selector = parsed
    if selector is not None:
        return None
    return path_id


def _range_path_ids_from_locator(locator: Any) -> tuple[str, str] | None:
    if not isinstance(locator, str):
        return None
    match = RANGE_LOCATOR_RE.fullmatch(locator.strip())
    if match is None:
        return None
    return match.group("start"), match.group("end")


def _directory_path_id_from_locator(locator: Any) -> str | None:
    if locator in ("", None):
        return "0000"
    if isinstance(locator, str) and locator.strip() == "/":
        return "0000"
    return _block_path_id_from_locator(locator)


def _parse_evidence_locator(locator: Any) -> tuple[str, str | None] | None:
    if not isinstance(locator, str):
        return None
    match = EVIDENCE_LOCATOR_RE.fullmatch(locator.strip())
    if match is None:
        return None
    return match.group("path_id"), match.group("selector")


def _block_link(path_id: str) -> str:
    return f"evidence://{path_id}"


def _inline_link(path_id: str, selector: str) -> str:
    return f"{_block_link(path_id)}/{selector}"


def _inline_links(evidence: list[dict[str, Any]] | None) -> list[str]:
    links: list[str] = []
    for selector in evidence or []:
        if not isinstance(selector, dict):
            continue
        path_id = selector.get("path_id")
        if not isinstance(path_id, str):
            continue
        for key in ("sentences", "items", "rows"):
            values = selector.get(key)
            if isinstance(values, list):
                links.extend(_inline_link(path_id, str(value)) for value in values)
    return links


def _expose_read_result(result: dict[str, Any]) -> dict[str, Any]:
    exposed: dict[str, Any] = {}
    for key, value in result.items():
        if key == "path_id" and isinstance(value, str):
            exposed["locator"] = _block_link(value)
        elif key == "returned_path_ids" and isinstance(value, list):
            exposed["returned_locators"] = [_block_link(item) if isinstance(item, str) else item for item in value]
            exposed[key] = value
        elif key == "blocks" and isinstance(value, list):
            exposed["blocks"] = [_expose_read_result(block) if isinstance(block, dict) else block for block in value]
        elif key == "text" and isinstance(value, str):
            exposed["text"] = _link_locator_text(value)
        else:
            exposed[key] = value
    return exposed


def _link_locator_text(text: str) -> str:
    linked_lines: list[str] = []
    for line in text.splitlines():
        linked = re.sub(
            r"^([│\s]*(?:[├└]── )?)(\d{4}(?:\.\d{4})*)\b",
            lambda match: f"{match.group(1)}{_block_link(match.group(2))}",
            line,
        )
        linked = re.sub(
            r"^path_id:\s*(\d{4}(?:\.\d{4})*)\s*$",
            lambda match: f"locator: {_block_link(match.group(1))}",
            linked,
        )
        linked = re.sub(
            r"^(## )(\d{4}(?:\.\d{4})*)(.*)$",
            lambda match: f"{match.group(1)}{_block_link(match.group(2))}{match.group(3)}",
            linked,
        )
        linked_lines.append(linked)
    return "\n".join(linked_lines)


def _evidence_texts_for_tool(evidence_texts: list[dict[str, str]]) -> list[dict[str, str]]:
    exposed = []
    for item in evidence_texts:
        path_id = item.get("path_id")
        selector = item.get("selector")
        locator = _inline_link(path_id, selector) if path_id and selector else ""
        exposed.append({"locator": locator, "selector": selector or "", "text": item.get("text", "")})
    return exposed


def _run_tool(state: Any, tool_name: str, args: dict[str, Any], execute: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    _emit_event(
        state,
        {
            "type": "tool_started",
            "tool": tool_name,
            "args": args,
        },
    )
    try:
        result = execute()
    except Exception as exc:  # pragma: no cover - exercised by tool users
        result = {"ok": False, "errors": [{"message": str(exc)}]}
    event_type = "tool_completed" if result.get("ok") is not False else "tool_failed"
    _record_action(state, tool_name, args, result)
    _emit_event(
        state,
        {
            "type": event_type,
            "tool": tool_name,
            "args": args,
            "result": result,
        },
    )
    return result


def _record_action(state: Any, tool_name: str, args: dict[str, Any], result: dict[str, Any]) -> None:
    state.actions.append(
        {
            "tool_name": tool_name,
            "args": args,
            "result": result,
        }
    )


def _emit_event(state: Any, payload: dict[str, Any]) -> None:
    event = {"seq": state.next_seq, **payload}
    state.next_seq += 1
    state.events.append(event)


__all__ = [
    "build_tools",
    "model_ls_text",
    "_ls",
    "_grep",
    "_read",
    "_inspect",
]
