"""Build a read-only virtual tree from semantic HTML documents."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import unquote


HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
BLOCK_TAGS = {"p", "ul", "ol", "table"}
DEFAULT_SNIPPET_CHARS = 24
DEFAULT_READ_LIMIT = 30
MAX_READ_LIMIT = 100
READABLE_KINDS = {"paragraph", "list", "table"}


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
    path_id: str
    kind: str
    display_name: str | None = None
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
    nodes_by_path_id: dict[str, VirtualNode]
    source_documents: list[SourceDocument]

    def resolve_path(self, path: str) -> str:
        return self._node(path).path

    def resolve_path_id(self, path_id: str) -> str:
        return self._node_by_path_id(path_id).path

    def path_id(self, path: str) -> str:
        if not is_path_id(path):
            return self._node(path).path_id
        return self._node_by_path_id(path).path_id

    def canonical_path_id(self, path_id: str) -> str:
        if not is_path_id(path_id):
            raise ValueError(f"invalid path_id: {path_id}")
        return self._node_by_path_id(path_id).path_id

    def tree_text(self, path: str = "/", depth: int = 3) -> str:
        node = self._node(path)
        max_depth = max(0, int(depth))
        lines = [f"{node.path_id} /" if node.path == "/" else f"{node.path_id} {display_name(node)}/"]
        if max_depth > 0:
            self._append_tree_lines(node, lines, prefix="", depth=max_depth)
        return "\n".join(lines)

    def read_markdown(
        self,
        path: str,
        *,
        offset: int = 0,
        limit: int = 0,
    ) -> dict[str, Any]:
        node = self._node(path)
        if node.kind == "paragraph":
            return {"path_id": node.path_id, "kind": "paragraph", "text": node.text}
        if node.kind == "list":
            return self._read_list(node, offset=offset, limit=limit)
        if node.kind == "table":
            return self._read_table(node, offset=offset, limit=limit)
        raise ValueError(f"path is not readable: {path}")

    def read_sequence(
        self,
        path: str,
        *,
        count: int,
        offset: int = 0,
        limit: int = 0,
    ) -> dict[str, Any]:
        start = self._node(path)
        if start.kind not in READABLE_KINDS:
            raise ValueError(f"path is not readable: {path}")
        parent = self._parent_node(start)
        siblings = parent.children
        start_index = siblings.index(start)
        requested_count = int(count)
        bounded_count = max(1, min(3, requested_count))
        selected: list[VirtualNode] = []
        has_more_in_section = False
        for sibling in siblings[start_index:]:
            if sibling.kind not in READABLE_KINDS:
                break
            if len(selected) >= bounded_count:
                has_more_in_section = True
                break
            selected.append(sibling)
        blocks = [self.read_markdown(node.path, offset=offset, limit=limit) for node in selected]
        return {
            "path_id": start.path_id,
            "kind": "read_sequence",
            "count_requested": requested_count,
            "count_limit": 3,
            "count_returned": len(blocks),
            "returned_path_ids": [block["path_id"] for block in blocks],
            "blocks": blocks,
            "text": render_read_sequence_text(blocks),
            "has_more_in_section": has_more_in_section,
        }

    def paragraph_anchors(self, path: str) -> list[dict[str, str]]:
        node = self._node(path)
        if node.kind != "paragraph":
            raise ValueError("anchors only supports .md paragraph files")
        return [
            {"id": f"S{index:03d}", "preview": sentence}
            for index, sentence in enumerate(split_sentences(node.text), start=1)
        ]

    def file_kind(self, path: str) -> str:
        node = self._node(path)
        if node.kind not in {"paragraph", "list", "table"}:
            raise ValueError(f"path is not readable: {path}")
        return node.kind

    def inline_selector_for_path(self, path: str) -> dict[str, Any]:
        node = self._node(path)
        if node.kind == "paragraph":
            return {"path_id": node.path_id, "sentences": [anchor["id"] for anchor in self.paragraph_anchors(node.path)]}
        if node.kind == "list":
            return {"path_id": node.path_id, "items": [item["id"] for item in node.list_items]}
        if node.kind == "table":
            table = node.table or {"rows": []}
            return {"path_id": node.path_id, "rows": [row["row_id"] for row in table["rows"]]}
        raise ValueError(f"path is not readable: {path}")

    def source_selectors(self) -> dict[str, str]:
        selectors: dict[str, str] = {}
        for path_id, node in self.nodes_by_path_id.items():
            source_id = source_dom_id(node.source)
            if source_id:
                selectors[path_id] = source_id
        return selectors

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
            path_id=node.path_id,
            title=node.title or node.name,
            columns=table["columns"],
            rows=visible_rows,
            total=len(rows),
            offset=bounded_offset,
            selected_columns=visible_rows[0]["values"].keys() if visible_rows else table["columns"],
            extra_metadata={"sql": sql, "matched_rows": len(rows)},
        )
        return {
            "path_id": node.path_id,
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
            path_id = selector.get("path_id")
            if not isinstance(path_id, str):
                errors.append({"index": index, "message": "unknown evidence path_id"})
                continue
            try:
                node = self._node_by_path_id(path_id)
            except ValueError:
                errors.append({"index": index, "message": "unknown evidence path_id"})
                continue
            if node.kind == "paragraph":
                errors.extend(validate_selector_values(index, selector, "sentences", [a["id"] for a in self.paragraph_anchors(node.path)]))
            elif node.kind == "list":
                errors.extend(validate_selector_values(index, selector, "items", [item["id"] for item in node.list_items]))
            elif node.kind == "table":
                table = node.table or {"rows": []}
                errors.extend(validate_selector_values(index, selector, "rows", [row["row_id"] for row in table["rows"]]))
            else:
                errors.append({"index": index, "message": "evidence path_id must point to a file"})
        return errors

    def canonicalize_evidence(self, evidence: Any) -> Any:
        if not isinstance(evidence, list):
            return evidence
        canonicalized: list[Any] = []
        for selector in evidence:
            if not isinstance(selector, dict):
                canonicalized.append(selector)
                continue
            path_id = selector.get("path_id")
            if not isinstance(path_id, str):
                canonicalized.append(selector)
                continue
            try:
                canonicalized.append({**selector, "path_id": self.canonical_path_id(path_id)})
            except ValueError:
                canonicalized.append(selector)
        return canonicalized

    def evidence_texts(self, evidence: list[dict[str, Any]]) -> list[dict[str, str]]:
        texts: list[dict[str, str]] = []
        for selector in evidence:
            locator = selector.get("path_id") or selector.get("path")
            node = self._node(locator)
            if node.kind == "paragraph":
                sentences = {item["id"]: item["preview"] for item in self.paragraph_anchors(node.path)}
                for sentence_id in selector.get("sentences", []) or []:
                    texts.append({"path_id": node.path_id, "selector": sentence_id, "text": sentences.get(sentence_id, "")})
            elif node.kind == "list":
                items = {item["id"]: item["text"] for item in node.list_items}
                for item_id in selector.get("items", []) or []:
                    texts.append({"path_id": node.path_id, "selector": item_id, "text": items.get(item_id, "")})
            elif node.kind == "table":
                rows = {row["row_id"]: " | ".join(str(value) for value in row["values"].values()) for row in (node.table or {}).get("rows", [])}
                for row_id in selector.get("rows", []) or []:
                    texts.append({"path_id": node.path_id, "selector": row_id, "text": rows.get(row_id, "")})
        return texts

    def _node(self, path: str) -> VirtualNode:
        if is_path_id(path):
            return self._node_by_path_id(path)
        normalized = normalize_path(path)
        node = self.nodes_by_path.get(normalized)
        if node is not None:
            return node
        decoded = normalize_path(unquote(normalized))
        node = self.nodes_by_path.get(decoded)
        if node is not None:
            return node
        raise ValueError(f"unknown path: {path}")

    def _node_by_path_id(self, path_id: str) -> VirtualNode:
        normalized = normalize_path_id(path_id)
        node = self.nodes_by_path_id.get(normalized)
        if node is not None:
            return node
        raise ValueError(f"unknown path_id: {path_id}")

    def _parent_node(self, node: VirtualNode) -> VirtualNode:
        parent_path = node.path.rsplit("/", 1)[0] or "/"
        parent = self.nodes_by_path.get(parent_path)
        if parent is None:
            raise ValueError(f"missing parent for path: {node.path}")
        return parent

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
            lines.append(f"{prefix}{connector}{child.path_id} {display_name(child)}{suffix}")
            extension = "    " if index == len(node.children) - 1 else "│   "
            self._append_tree_lines(child, lines, prefix=prefix + extension, depth=depth - 1)

    def _read_list(self, node: VirtualNode, *, offset: int, limit: int) -> dict[str, Any]:
        top_level_items = [item for item in node.list_items if "." not in item["id"][1:]]
        bounded_offset, bounded_limit = normalize_window(offset, limit, total=len(top_level_items))
        visible = top_level_items[bounded_offset : bounded_offset + bounded_limit]
        allowed_prefixes = {item["id"] for item in visible}
        rendered_items = [
            item
            for item in node.list_items
            if item["id"] in allowed_prefixes or any(item["id"].startswith(prefix + ".") for prefix in allowed_prefixes)
        ]
        text = render_list_markdown(node, rendered_items, offset=bounded_offset, total=len(top_level_items))
        return {
            "path_id": node.path_id,
            "kind": "list",
            "text": text,
            "offset": bounded_offset,
            "limit": bounded_limit,
            "total": len(node.list_items),
            "has_more": bounded_offset + bounded_limit < len(top_level_items),
        }

    def _read_table(self, node: VirtualNode, *, offset: int, limit: int) -> dict[str, Any]:
        table = node.table or {"columns": [], "rows": []}
        bounded_offset, bounded_limit = normalize_window(offset, limit, total=len(table["rows"]))
        visible_rows = table["rows"][bounded_offset : bounded_offset + bounded_limit]
        text = render_table_markdown(
            kind="table",
            path_id=node.path_id,
            title=node.title or node.name,
            columns=table["columns"],
            rows=visible_rows,
            total=len(table["rows"]),
            offset=bounded_offset,
            selected_columns=table["columns"],
        )
        return {
            "path_id": node.path_id,
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
    root = VirtualNode(name="", path="/", path_id="0000", kind="root")
    nodes_by_path = {"/": root}
    nodes_by_path_id = {root.path_id: root}
    used_root_names: dict[str, int] = {}

    for document_index, source in enumerate(source_documents, start=1):
        parsed_root = parse_html(source.html)
        title = document_title(parsed_root)
        basename = slug_text(Path(source.filename).stem or "document")
        title_slug = slug_text(title) if title else ""
        base_name = f"{document_index:03d}-{basename}" + (f"-{title_slug}" if title_slug else "")
        doc_name = unique_name(base_name, used_root_names)
        doc_path = f"/{doc_name}"
        doc_node = VirtualNode(
            name=doc_name,
            path=doc_path,
            path_id=child_path_id(root.path_id, len(root.children) + 1),
            display_name=decode_display_name(f"{basename}" + (f"-{title_slug}" if title_slug else "")),
            kind="document",
            source=parsed_root,
            source_document=source.filename,
            title=title,
        )
        root.children.append(doc_node)
        nodes_by_path[doc_path] = doc_node
        nodes_by_path_id[doc_node.path_id] = doc_node
        add_document_children(doc_node, parsed_root, nodes_by_path, nodes_by_path_id)

    return HtmlDocument(
        virtual_root=root,
        nodes_by_path=nodes_by_path,
        nodes_by_path_id=nodes_by_path_id,
        source_documents=source_documents,
    )


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
    nodes_by_path_id: dict[str, VirtualNode],
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
            section = add_virtual_child(parent, name, "section", nodes_by_path, nodes_by_path_id, source=node, text=node_text(node))
            sibling_counters[section.path] = {}
            section_stack.append((level, section))
            continue

        parent = section_stack[-1][1] if section_stack else doc_node
        if node.tag == "p":
            text = node_text(node)
            name = numbered_name(parent, paragraph_slug(text), sibling_counters, suffix=".md")
            add_virtual_child(parent, name, "paragraph", nodes_by_path, nodes_by_path_id, source=node, text=text)
        elif node.tag in {"ul", "ol"}:
            items = list_items(node)
            title = slug_text(items[0]["text"][:DEFAULT_SNIPPET_CHARS]) if items else "list"
            name = numbered_name(parent, title or "list", sibling_counters, suffix=".list")
            child = add_virtual_child(parent, name, "list", nodes_by_path, nodes_by_path_id, source=node, title=title or "list")
            child.list_items = items
        elif node.tag == "table":
            table = parse_table(node)
            title = slug_text(table.get("label") or " ".join(table["columns"][:3]) or "table")
            name = numbered_name(parent, title or "table", sibling_counters, suffix=".table")
            child = add_virtual_child(parent, name, "table", nodes_by_path, nodes_by_path_id, source=node, title=table.get("label") or title)
            child.table = table


def add_virtual_child(
    parent: VirtualNode,
    name: str,
    kind: str,
    nodes_by_path: dict[str, VirtualNode],
    nodes_by_path_id: dict[str, VirtualNode],
    *,
    source: HtmlNode | None = None,
    title: str | None = None,
    text: str = "",
) -> VirtualNode:
    path = parent.path.rstrip("/") + "/" + name
    visible_name = decode_display_name(strip_ordinal_prefix(name))
    child = VirtualNode(
        name=name,
        path=path,
        path_id=child_path_id(parent.path_id, len(parent.children) + 1),
        display_name=visible_name,
        kind=kind,
        source=source,
        source_document=parent.source_document,
        title=title,
        text=text,
    )
    parent.children.append(child)
    nodes_by_path[path] = child
    nodes_by_path_id[child.path_id] = child
    return child


def source_dom_id(node: HtmlNode | None) -> str:
    if node is None:
        return ""
    for attr_name in ("id", "data-element-id"):
        value = node.attrs.get(attr_name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


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
        f"path_id: {node.path_id}",
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
    path_id: str,
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
        f"path_id: {path_id}",
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


def render_read_sequence_text(blocks: list[dict[str, Any]]) -> str:
    rendered: list[str] = []
    for block in blocks:
        rendered.extend(
            [
                f"## {block.get('path_id', '')} ({block.get('kind', 'unknown')})",
                "",
                str(block.get("text", "")),
            ]
        )
    return "\n\n".join(rendered)


def validate_selector_values(index: int, selector: dict[str, Any], key: str, allowed: list[str]) -> list[dict[str, Any]]:
    if key not in selector:
        return [{"index": index, "message": f"evidence selector for this path_id must use {key}"}]
    values = selector.get(key)
    if not isinstance(values, list) or not values:
        return [{"index": index, "message": f"{key} must be a non-empty list"}]
    errors = []
    for value in values:
        if value not in allowed:
            errors.append({"index": index, "message": f"unknown {key} value: {value}"})
    return errors


def normalize_window(offset: int, limit: int, *, total: int | None = None) -> tuple[int, int]:
    try:
        normalized_offset = max(0, int(offset))
    except (TypeError, ValueError):
        normalized_offset = 0
    try:
        normalized_limit = int(limit)
    except (TypeError, ValueError):
        normalized_limit = DEFAULT_READ_LIMIT
    if normalized_limit <= 0 and total is not None:
        return normalized_offset, max(0, total - normalized_offset)
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


def display_name(node: VirtualNode) -> str:
    return node.display_name or strip_ordinal_prefix(node.name)


def strip_ordinal_prefix(name: str) -> str:
    return re.sub(r"^\d{3}-", "", name)


def decode_display_name(name: str) -> str:
    return unquote(name)


def normalize_path(path: str) -> str:
    normalized = "/" + str(path or "/").strip("/")
    return "/" if normalized == "/" else normalized


def child_path_id(parent_path_id: str, index: int) -> str:
    prefix = normalize_path_id(parent_path_id)
    return f"{prefix}.{index:04d}"


def is_path_id(value: str) -> bool:
    normalized = str(value or "").strip()
    return bool(re.fullmatch(r"\d{4}(?:\.\d{4})*", normalized))


def normalize_path_id(path_id: str) -> str:
    normalized = str(path_id or "").strip()
    if not re.fullmatch(r"\d{4}(?:\.\d{4})*", normalized):
        raise ValueError(f"invalid path_id: {path_id}")
    return normalized


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
