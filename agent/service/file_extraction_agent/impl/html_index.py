"""Build a read-only virtual tree from semantic HTML documents."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
BLOCK_TAGS = {"p", "ul", "ol", "table"}
DEFAULT_SNIPPET_CHARS = 24
DEFAULT_READ_LIMIT = 30
MAX_READ_LIMIT = 100


@dataclass
class SourceDocument:
    filename: str
    html: str


@dataclass
class HtmlNode:
    tag: str | None
    attrs: dict[str, str] = field(default_factory=dict)
    children: list["HtmlNode"] = field(default_factory=list)
    text: str = ""
    parent: "HtmlNode | None" = None


@dataclass
class VirtualNode:
    name: str
    path: str
    kind: str
    source: HtmlNode | None = None
    source_document: str | None = None
    title: str | None = None
    text: str = ""
    children: list["VirtualNode"] = field(default_factory=list)
    list_items: list[dict[str, Any]] = field(default_factory=list)
    table: dict[str, Any] | None = None


@dataclass
class HtmlDocument:
    virtual_root: VirtualNode
    nodes_by_path: dict[str, VirtualNode]
    source_documents: list[SourceDocument]

    def tree_text(self, path: str = "/", depth: int = 3) -> str:
        node = self._node(path)
        max_depth = max(0, int(depth))
        lines = [node.path if node.path == "/" else f"{node.path}/"]
        if max_depth > 0:
            self._append_tree_lines(node, lines, prefix="", depth=max_depth)
        return "\n".join(lines)

    def read_markdown(
        self,
        path: str,
        *,
        offset: int = 0,
        limit: int = DEFAULT_READ_LIMIT,
    ) -> dict[str, Any]:
        node = self._node(path)
        if node.kind == "paragraph":
            return {"path": node.path, "kind": "paragraph", "text": node.text}
        if node.kind == "list":
            return self._read_list(node, offset=offset, limit=limit)
        if node.kind == "table":
            return self._read_table(node, offset=offset, limit=limit)
        raise ValueError(f"path is not readable: {path}")

    def paragraph_anchors(self, path: str) -> list[dict[str, str]]:
        node = self._node(path)
        if node.kind != "paragraph":
            raise ValueError("anchors only supports .md paragraph files")
        return [
            {"id": f"S{index:03d}", "preview": sentence}
            for index, sentence in enumerate(split_sentences(node.text), start=1)
        ]

    def query_table(
        self,
        path: str,
        sql: str,
        *,
        offset: int = 0,
        limit: int = DEFAULT_READ_LIMIT,
    ) -> dict[str, Any]:
        node = self._node(path)
        if node.kind != "table":
            raise ValueError("query_table only supports .table paths")
        table = node.table or {"columns": [], "rows": []}
        rows = query_table_rows(table, sql)
        bounded_offset, bounded_limit = normalize_window(offset, limit)
        visible_rows = rows[bounded_offset : bounded_offset + bounded_limit]
        text = render_table_markdown(
            kind="table_query",
            path=node.path,
            title=node.title or node.name,
            columns=table["columns"],
            rows=visible_rows,
            total=len(rows),
            offset=bounded_offset,
            selected_columns=visible_rows[0]["values"].keys() if visible_rows else table["columns"],
            extra_metadata={"sql": sql, "matched_rows": len(rows)},
        )
        return {
            "path": node.path,
            "kind": "table_query",
            "text": text,
            "offset": bounded_offset,
            "limit": bounded_limit,
            "total": len(rows),
            "has_more": bounded_offset + bounded_limit < len(rows),
        }

    def validate_evidence(self, evidence: Any) -> list[dict[str, Any]]:
        errors: list[dict[str, Any]] = []
        if not isinstance(evidence, list):
            return [{"message": "evidence must be a list"}]
        for index, selector in enumerate(evidence):
            if not isinstance(selector, dict):
                errors.append({"index": index, "message": "evidence selector must be an object"})
                continue
            path = selector.get("path")
            if not isinstance(path, str) or path not in self.nodes_by_path:
                errors.append({"index": index, "message": "unknown evidence path"})
                continue
            node = self.nodes_by_path[path]
            if node.kind == "paragraph":
                errors.extend(validate_selector_values(index, selector, "sentences", [a["id"] for a in self.paragraph_anchors(path)]))
            elif node.kind == "list":
                errors.extend(validate_selector_values(index, selector, "items", [item["id"] for item in node.list_items]))
            elif node.kind == "table":
                table = node.table or {"rows": []}
                errors.extend(validate_selector_values(index, selector, "rows", [row["row_id"] for row in table["rows"]]))
            else:
                errors.append({"index": index, "message": "evidence path must point to a file"})
        return errors

    def evidence_texts(self, evidence: list[dict[str, Any]]) -> list[dict[str, str]]:
        texts: list[dict[str, str]] = []
        for selector in evidence:
            node = self.nodes_by_path[selector["path"]]
            if node.kind == "paragraph":
                sentences = {item["id"]: item["preview"] for item in self.paragraph_anchors(node.path)}
                for sentence_id in selector.get("sentences", []) or []:
                    texts.append({"path": node.path, "selector": sentence_id, "text": sentences.get(sentence_id, "")})
            elif node.kind == "list":
                items = {item["id"]: item["text"] for item in node.list_items}
                for item_id in selector.get("items", []) or []:
                    texts.append({"path": node.path, "selector": item_id, "text": items.get(item_id, "")})
            elif node.kind == "table":
                rows = {row["row_id"]: " | ".join(str(value) for value in row["values"].values()) for row in (node.table or {}).get("rows", [])}
                for row_id in selector.get("rows", []) or []:
                    texts.append({"path": node.path, "selector": row_id, "text": rows.get(row_id, "")})
        return texts

    def _node(self, path: str) -> VirtualNode:
        try:
            return self.nodes_by_path[normalize_path(path)]
        except KeyError as exc:
            raise ValueError(f"unknown path: {path}") from exc

    def _append_tree_lines(
        self,
        node: VirtualNode,
        lines: list[str],
        *,
        prefix: str,
        depth: int,
    ) -> None:
        if depth <= 0:
            return
        for index, child in enumerate(node.children):
            connector = "└── " if index == len(node.children) - 1 else "├── "
            suffix = "/" if child.kind in {"root", "document", "section"} else ""
            lines.append(f"{prefix}{connector}{child.name}{suffix}")
            extension = "    " if index == len(node.children) - 1 else "│   "
            self._append_tree_lines(child, lines, prefix=prefix + extension, depth=depth - 1)

    def _read_list(self, node: VirtualNode, *, offset: int, limit: int) -> dict[str, Any]:
        bounded_offset, bounded_limit = normalize_window(offset, limit)
        top_level_items = [item for item in node.list_items if "." not in item["id"][1:]]
        visible = top_level_items[bounded_offset : bounded_offset + bounded_limit]
        allowed_prefixes = {item["id"] for item in visible}
        rendered_items = [
            item
            for item in node.list_items
            if item["id"] in allowed_prefixes or any(item["id"].startswith(prefix + ".") for prefix in allowed_prefixes)
        ]
        text = render_list_markdown(node, rendered_items, offset=bounded_offset, total=len(top_level_items))
        return {
            "path": node.path,
            "kind": "list",
            "text": text,
            "offset": bounded_offset,
            "limit": bounded_limit,
            "total": len(node.list_items),
            "has_more": bounded_offset + bounded_limit < len(top_level_items),
        }

    def _read_table(self, node: VirtualNode, *, offset: int, limit: int) -> dict[str, Any]:
        table = node.table or {"columns": [], "rows": []}
        bounded_offset, bounded_limit = normalize_window(offset, limit)
        visible_rows = table["rows"][bounded_offset : bounded_offset + bounded_limit]
        text = render_table_markdown(
            kind="table",
            path=node.path,
            title=node.title or node.name,
            columns=table["columns"],
            rows=visible_rows,
            total=len(table["rows"]),
            offset=bounded_offset,
            selected_columns=table["columns"],
        )
        return {
            "path": node.path,
            "kind": "table",
            "text": text,
            "offset": bounded_offset,
            "limit": bounded_limit,
            "total": len(table["rows"]),
            "has_more": bounded_offset + bounded_limit < len(table["rows"]),
        }


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = HtmlNode(tag=None)
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = HtmlNode(tag=tag.lower(), attrs={key.lower(): value or "" for key, value in attrs})
        node.parent = self.stack[-1]
        self.stack[-1].children.append(node)
        if tag.lower() not in {"br", "meta", "link", "img"}:
            self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if data:
            node = HtmlNode(tag=None, text=data)
            node.parent = self.stack[-1]
            self.stack[-1].children.append(node)


def build_html_document(documents: Any) -> HtmlDocument:
    source_documents = normalize_documents(documents)
    root = VirtualNode(name="", path="/", kind="root")
    nodes_by_path = {"/": root}
    used_root_names: dict[str, int] = {}

    for document_index, source in enumerate(source_documents, start=1):
        parsed_root = parse_html(source.html)
        title = document_title(parsed_root)
        basename = slug_text(Path(source.filename).stem or "document")
        title_slug = slug_text(title) if title else ""
        base_name = f"{document_index:03d}-{basename}" + (f"-{title_slug}" if title_slug else "")
        doc_name = unique_name(base_name, used_root_names)
        doc_path = f"/{doc_name}"
        doc_node = VirtualNode(name=doc_name, path=doc_path, kind="document", source=parsed_root, source_document=source.filename, title=title)
        root.children.append(doc_node)
        nodes_by_path[doc_path] = doc_node
        add_document_children(doc_node, parsed_root, nodes_by_path)

    return HtmlDocument(virtual_root=root, nodes_by_path=nodes_by_path, source_documents=source_documents)


def normalize_documents(documents: Any) -> list[SourceDocument]:
    if not isinstance(documents, list) or not documents:
        raise ValueError("documents must be a non-empty list")
    normalized: list[SourceDocument] = []
    for index, item in enumerate(documents, start=1):
        filename = item.get("filename") if isinstance(item, dict) else getattr(item, "filename", None)
        html = item.get("html") if isinstance(item, dict) else getattr(item, "html", None)
        if not isinstance(filename, str) or not filename.strip():
            raise ValueError(f"documents[{index}].filename is required")
        if not isinstance(html, str) or not html.strip():
            raise ValueError(f"documents[{index}].html must be a non-empty string")
        normalized.append(SourceDocument(filename=filename.strip(), html=html))
    return normalized


def parse_html(html: str) -> HtmlNode:
    parser = _Parser()
    parser.feed(html)
    parser.close()
    return parser.root


def add_document_children(
    doc_node: VirtualNode,
    parsed_root: HtmlNode,
    nodes_by_path: dict[str, VirtualNode],
) -> None:
    section_stack: list[tuple[int, VirtualNode]] = [(0, doc_node)]
    sibling_counters: dict[str, dict[str, int]] = {doc_node.path: {}}

    for node in block_nodes(parsed_root):
        if node.tag == "h1":
            continue
        if node.tag in HEADING_TAGS:
            level = int(node.tag[1])
            while section_stack and section_stack[-1][0] >= level:
                section_stack.pop()
            parent = section_stack[-1][1] if section_stack else doc_node
            name = numbered_name(parent, slug_text(node_text(node)) or "section", sibling_counters, suffix="")
            section = add_virtual_child(parent, name, "section", nodes_by_path, source=node, text=node_text(node))
            sibling_counters[section.path] = {}
            section_stack.append((level, section))
            continue

        parent = section_stack[-1][1] if section_stack else doc_node
        if node.tag == "p":
            text = node_text(node)
            name = numbered_name(parent, paragraph_slug(text), sibling_counters, suffix=".md")
            add_virtual_child(parent, name, "paragraph", nodes_by_path, source=node, text=text)
        elif node.tag in {"ul", "ol"}:
            items = list_items(node)
            title = slug_text(items[0]["text"][:DEFAULT_SNIPPET_CHARS]) if items else "list"
            name = numbered_name(parent, title or "list", sibling_counters, suffix=".list")
            child = add_virtual_child(parent, name, "list", nodes_by_path, source=node, title=title or "list")
            child.list_items = items
        elif node.tag == "table":
            table = parse_table(node)
            title = slug_text(table.get("label") or " ".join(table["columns"][:3]) or "table")
            name = numbered_name(parent, title or "table", sibling_counters, suffix=".table")
            child = add_virtual_child(parent, name, "table", nodes_by_path, source=node, title=table.get("label") or title)
            child.table = table


def add_virtual_child(
    parent: VirtualNode,
    name: str,
    kind: str,
    nodes_by_path: dict[str, VirtualNode],
    *,
    source: HtmlNode | None = None,
    title: str | None = None,
    text: str = "",
) -> VirtualNode:
    path = parent.path.rstrip("/") + "/" + name
    child = VirtualNode(name=name, path=path, kind=kind, source=source, source_document=parent.source_document, title=title, text=text)
    parent.children.append(child)
    nodes_by_path[path] = child
    return child


def block_nodes(root: HtmlNode) -> list[HtmlNode]:
    result: list[HtmlNode] = []

    def visit(node: HtmlNode, *, inside_block: bool = False) -> None:
        if node.tag in HEADING_TAGS or node.tag in BLOCK_TAGS:
            result.append(node)
            return
        for child in node.children:
            if child.tag is not None:
                visit(child, inside_block=inside_block)

    visit(root)
    return result


def document_title(root: HtmlNode) -> str:
    for node in walk(root):
        if node.tag in {"h1", "title"}:
            text = node_text(node)
            if text:
                return text
    return ""


def list_items(node: HtmlNode) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    top_items = [child for child in node.children if child.tag == "li"]
    for index, item in enumerate(top_items, start=1):
        collect_list_item(item, f"I{index:03d}", items, depth=0)
    return items


def collect_list_item(node: HtmlNode, item_id: str, items: list[dict[str, Any]], *, depth: int) -> None:
    text = direct_text_without_nested_lists(node)
    nested_lists = [child for child in node.children if child.tag in {"ul", "ol"}]
    nested_text = " ".join(node_text(child) for child in nested_lists)
    display_text = " ".join(part for part in [text, nested_text] if part).strip()
    items.append({"id": item_id, "text": display_text or text, "depth": depth})
    nested_index = 1
    for nested in nested_lists:
        for child in [item for item in nested.children if item.tag == "li"]:
            collect_list_item(child, f"{item_id}.{nested_index:03d}", items, depth=depth + 1)
            nested_index += 1


def direct_text_without_nested_lists(node: HtmlNode) -> str:
    parts: list[str] = []
    for child in node.children:
        if child.tag in {"ul", "ol"}:
            continue
        parts.append(node_text(child))
    return " ".join(" ".join(parts).split())


def parse_table(node: HtmlNode) -> dict[str, Any]:
    label = ""
    rows: list[list[str]] = []
    for child in walk(node):
        if child.tag == "caption" and not label:
            label = node_text(child)
        if child.tag == "tr":
            cells = [node_text(grandchild) for grandchild in child.children if grandchild.tag in {"th", "td"}]
            if cells:
                rows.append(cells)
    columns = rows[0] if rows else []
    data_rows = rows[1:] if rows else []
    parsed_rows: list[dict[str, Any]] = []
    for index, row in enumerate(data_rows, start=1):
        values = {
            column: row[column_index] if column_index < len(row) else ""
            for column_index, column in enumerate(columns)
        }
        parsed_rows.append({"row_id": f"R{index:03d}", "values": values})
    return {"label": label, "columns": columns, "rows": parsed_rows}


def query_table_rows(table: dict[str, Any], sql: str) -> list[dict[str, Any]]:
    if not isinstance(sql, str) or not sql.strip().lower().startswith("select"):
        raise ValueError("query_table only allows SELECT statements")
    if ";" in sql.strip().rstrip(";"):
        raise ValueError("query_table only allows a single SELECT statement")
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    columns = table["columns"]
    column_defs = ", ".join(f'"{column}" TEXT' for column in columns)
    quoted_columns = ", ".join(f'"{column}"' for column in columns)
    connection.execute(f'CREATE TABLE data ({column_defs})')
    for row in table["rows"]:
        placeholders = ", ".join("?" for _ in columns)
        connection.execute(
            f"INSERT INTO data ({quoted_columns}) VALUES ({placeholders})",
            [row["values"].get(column, "") for column in columns],
        )
    selected = connection.execute(sql).fetchall()
    results: list[dict[str, Any]] = []
    for selected_row in selected:
        selected_values = dict(selected_row)
        for row in table["rows"]:
            if all(str(row["values"].get(key, "")) == str(value) for key, value in selected_values.items() if key in row["values"]):
                results.append({"row_id": row["row_id"], "values": selected_values})
                break
    connection.close()
    return results


def render_list_markdown(node: VirtualNode, items: list[dict[str, Any]], *, offset: int, total: int) -> str:
    showing_end = min(total, offset + len([item for item in items if item["depth"] == 0]))
    lines = [
        "---",
        "kind: list",
        f"path: {node.path}",
        f"title: {node.title or node.name}",
        f"items: {total}",
        f"showing: {offset + 1}-{showing_end}" if total else "showing: 0-0",
        "---",
        "",
    ]
    for item in items:
        indent = "  " * item["depth"]
        lines.append(f"{indent}- [{item['id']}] {item['text']}")
    return "\n".join(lines)


def render_table_markdown(
    *,
    kind: str,
    path: str,
    title: str,
    columns: list[str],
    rows: list[dict[str, Any]],
    total: int,
    offset: int,
    selected_columns: Any,
    extra_metadata: dict[str, Any] | None = None,
) -> str:
    selected = list(selected_columns)
    showing_end = min(total, offset + len(rows))
    lines = [
        "---",
        f"kind: {kind}",
        f"path: {path}",
        f"title: {title}",
        f"rows: {total}",
        "columns: " + " | ".join(columns),
    ]
    for key, value in (extra_metadata or {}).items():
        lines.append(f"{key}: {value}")
    lines.extend(
        [
            f"showing: {offset + 1}-{showing_end}" if total else "showing: 0-0",
            "---",
            "",
            "| row | " + " | ".join(selected) + " |",
            "| --- | " + " | ".join("---" for _ in selected) + " |",
        ]
    )
    for row in rows:
        lines.append("| " + row["row_id"] + " | " + " | ".join(str(row["values"].get(column, "")) for column in selected) + " |")
    return "\n".join(lines)


def validate_selector_values(index: int, selector: dict[str, Any], key: str, allowed: list[str]) -> list[dict[str, Any]]:
    if key not in selector:
        return [{"index": index, "message": f"evidence selector for this path must use {key}"}]
    values = selector.get(key)
    if not isinstance(values, list) or not values:
        return [{"index": index, "message": f"{key} must be a non-empty list"}]
    errors = []
    for value in values:
        if value not in allowed:
            errors.append({"index": index, "message": f"unknown {key} value: {value}"})
    return errors


def normalize_window(offset: int, limit: int) -> tuple[int, int]:
    try:
        normalized_offset = max(0, int(offset))
    except (TypeError, ValueError):
        normalized_offset = 0
    try:
        normalized_limit = int(limit)
    except (TypeError, ValueError):
        normalized_limit = DEFAULT_READ_LIMIT
    normalized_limit = max(1, min(normalized_limit, MAX_READ_LIMIT))
    return normalized_offset, normalized_limit


def numbered_name(parent: VirtualNode, slug: str, counters: dict[str, dict[str, int]], *, suffix: str) -> str:
    bucket = counters.setdefault(parent.path, {})
    ordinal = sum(bucket.values()) + 1
    base = f"{ordinal:03d}-{slug}{suffix}"
    bucket[base] = bucket.get(base, 0) + 1
    if bucket[base] == 1:
        return base
    stem = base[: -len(suffix)] if suffix else base
    return f"{stem}-{bucket[base]}{suffix}"


def unique_name(base: str, used: dict[str, int]) -> str:
    used[base] = used.get(base, 0) + 1
    if used[base] == 1:
        return base
    return f"{base}-{used[base]}"


def normalize_path(path: str) -> str:
    normalized = "/" + str(path or "/").strip("/")
    return "/" if normalized == "/" else normalized


def slug_text(text: str) -> str:
    normalized = " ".join(str(text or "").split())
    normalized = re.sub(r'[\\/:*?"<>|#]+', "-", normalized)
    normalized = normalized.strip(" .-_。；;，,、")
    return normalized[:60] or "empty"


def paragraph_slug(text: str) -> str:
    return slug_text(str(text or "")[:DEFAULT_SNIPPET_CHARS])


def node_text(node: HtmlNode) -> str:
    if node.tag is None:
        return " ".join(node.text.split())
    return " ".join(part for part in (node_text(child) for child in node.children) if part).strip()


def split_sentences(text: str) -> list[str]:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return []
    parts = re.findall(r".+?(?:[。！？!?；;.]|$)", normalized)
    return [part.strip() for part in parts if part.strip()]


def walk(node: HtmlNode):
    yield node
    for child in node.children:
        yield from walk(child)


__all__ = [
    "SourceDocument",
    "HtmlNode",
    "VirtualNode",
    "HtmlDocument",
    "build_html_document",
]
