"""Build runtime indexes from HTML that already contains stable ids."""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any


TRACKED_TAGS = {
    "figure",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "p",
    "li",
    "table",
    "tr",
    "caption",
    "ul",
    "ol",
}
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
TABLE_EVIDENCE_ID_TAGS = {"table", "tr"}
DEFAULT_ID_PREFIX = "dp"


@dataclass
class HtmlNode:
    tag: str | None
    attrs: dict[str, str] = field(default_factory=dict)
    children: list["HtmlNode"] = field(default_factory=list)
    text: str = ""
    parent: "HtmlNode | None" = None


@dataclass
class HtmlElement:
    id: str
    tag: str
    type: str
    text: str
    parent_id: str | None = None
    child_ids: list[str] = field(default_factory=list)


@dataclass
class HtmlTable:
    table_id: str
    columns: list[str]
    rows: list[dict[str, Any]]
    row_ids: list[str]
    header_row_id: str | None = None
    label: str | None = None


@dataclass
class HtmlDocument:
    elements_by_id: dict[str, HtmlElement]
    tree: list[dict[str, Any]]
    tables_by_id: dict[str, HtmlTable]
    row_index: dict[str, dict[str, Any]]


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = HtmlNode(tag=None)
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = HtmlNode(tag=tag.lower(), attrs={k.lower(): v or "" for k, v in attrs})
        node.parent = self.stack[-1]
        self.stack[-1].children.append(node)
        if tag.lower() not in {"br", "meta", "link"}:
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


def build_html_document(html: str) -> HtmlDocument:
    if not isinstance(html, str) or not html.strip():
        raise ValueError("html must be a non-empty string")

    parser = _Parser()
    parser.feed(html)
    parser.close()

    assign_missing_table_evidence_ids(parser.root)
    validate_required_ids(parser.root)
    elements_by_id = build_elements_by_id(parser.root)
    tables_by_id, row_index = build_tables_by_id(parser.root)
    tree = build_document_tree(parser.root, tables_by_id)
    return HtmlDocument(
        elements_by_id=elements_by_id,
        tree=tree,
        tables_by_id=tables_by_id,
        row_index=row_index,
    )


def assign_missing_table_evidence_ids(root: HtmlNode, *, prefix: str = DEFAULT_ID_PREFIX) -> None:
    """给缺少 id 的 table/tr 补稳定证据 id。"""

    counters: dict[str, int] = {}
    existing_ids = {
        node.attrs["id"]
        for node in walk(root)
        if node.tag is not None and node.attrs.get("id")
    }
    for node in walk(root):
        if (
            node.tag is None
            or node.tag not in TABLE_EVIDENCE_ID_TAGS
            or node.attrs.get("id")
        ):
            continue
        node.attrs["id"] = next_generated_id(
            prefix=prefix,
            id_name=node.tag,
            counters=counters,
            existing_ids=existing_ids,
        )
        owner = table_owner_node(node)
        if owner is not None and owner.attrs.get("id"):
            node.attrs["data-table-id"] = owner.attrs["id"]


def next_generated_id(
    *,
    prefix: str,
    id_name: str,
    counters: dict[str, int],
    existing_ids: set[str],
) -> str:
    while True:
        counters[id_name] = counters.get(id_name, 0) + 1
        candidate = f"{prefix}-{id_name}-{counters[id_name]}"
        if candidate not in existing_ids:
            existing_ids.add(candidate)
            return candidate


def validate_required_ids(root: HtmlNode) -> None:
    seen: set[str] = set()
    for node in walk(root):
        if node.tag is None:
            continue
        element_id = node.attrs.get("id")
        if element_id:
            if element_id in seen:
                raise ValueError(f"duplicate id: {element_id}")
            seen.add(element_id)
        if node.tag in TRACKED_TAGS and not element_id:
            raise ValueError(f"missing id for <{node.tag}> element")


def build_elements_by_id(root: HtmlNode) -> dict[str, HtmlElement]:
    indexed: dict[str, HtmlElement] = {}
    for node in walk(root):
        if node.tag is None:
            continue
        element_id = node.attrs.get("id")
        if not element_id:
            continue
        child_ids = [
            child.attrs["id"]
            for child in node.children
            if child.tag is not None and child.attrs.get("id")
        ]
        indexed[element_id] = HtmlElement(
            id=element_id,
            tag=node.tag,
            type=infer_node_type(node),
            text=node_text(node),
            parent_id=_parent_id(node),
            child_ids=child_ids,
        )
    return indexed


def build_document_tree(
    root: HtmlNode,
    tables_by_id: dict[str, HtmlTable],
) -> list[dict[str, Any]]:
    tree: list[dict[str, Any]] = []
    heading_stack: list[tuple[int, dict[str, Any]]] = []

    for node in walk(root):
        if node.tag is None or node.tag not in TRACKED_TAGS:
            continue
        if node.tag in {"tr", "ul", "ol", "p", "li", "caption"}:
            continue
        if node.tag == "table" and table_owner_node(node) is not None:
            continue
        element_id = node.attrs.get("id")
        if not element_id:
            continue
        if is_table_overview_node(node) and element_id not in tables_by_id:
            continue

        item = tree_node(node, tables_by_id)
        if node.tag in HEADING_TAGS:
            level = heading_level(node.tag)
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            if heading_stack:
                heading_stack[-1][1]["children"].append(item)
            else:
                tree.append(item)
            heading_stack.append((level, item))
            continue

        if heading_stack:
            heading_stack[-1][1]["children"].append(item)
        else:
            tree.append(item)

    return tree


def tree_node(node: HtmlNode, tables_by_id: dict[str, HtmlTable]) -> dict[str, Any]:
    element_id = node.attrs["id"]
    item: dict[str, Any] = {
        "id": element_id,
        "type": infer_node_type(node),
        "children": [],
    }
    if node.tag in HEADING_TAGS:
        item["text"] = node_text(node)
    if is_table_overview_node(node) and element_id in tables_by_id:
        table = tables_by_id[element_id]
        item["label"] = table.label
        item["columns"] = table.columns
        item["row_count"] = len(table.rows)
    return item


def build_tables_by_id(root: HtmlNode) -> tuple[dict[str, HtmlTable], dict[str, dict[str, Any]]]:
    tables: dict[str, HtmlTable] = {}
    row_index: dict[str, dict[str, Any]] = {}
    for node in walk(root):
        if node.tag != "table":
            continue
        table = parse_table(node)
        tables[table.table_id] = table
        for position, row_id in enumerate(table.row_ids):
            row_index[row_id] = {
                "table_id": table.table_id,
                "row_index": position,
                "row": table.rows[position],
            }
    return tables, row_index


def parse_table(table_node: HtmlNode) -> HtmlTable:
    owner = table_owner_node(table_node)
    table_id = (
        owner.attrs["id"]
        if owner is not None and owner.attrs.get("id")
        else table_node.attrs["id"]
    )
    rows = [node for node in walk(table_node) if node.tag == "tr"]
    if not rows:
        return HtmlTable(table_id=table_id, columns=[], rows=[], row_ids=[])

    header_index = next(
        (index for index, row in enumerate(rows) if any(child.tag == "th" for child in row.children)),
        0,
    )
    header_row = rows[header_index]
    columns = extract_table_columns(header_row)

    parsed_rows: list[dict[str, Any]] = []
    row_ids: list[str] = []
    for row in rows[header_index + 1 :]:
        cells = row_cells(row)
        values = {
            columns[index]: node_text(cell)
            for index, cell in enumerate(cells[: len(columns)])
        }
        parsed_rows.append(values)
        row_ids.append(row.attrs["id"])

    return HtmlTable(
        table_id=table_id,
        columns=columns,
        rows=parsed_rows,
        row_ids=row_ids,
        header_row_id=header_row.attrs.get("id"),
        label=table_label(table_node, owner),
    )


def extract_table_columns(row: HtmlNode) -> list[str]:
    columns: list[str] = []
    seen: dict[str, int] = {}
    for index, cell in enumerate(row_cells(row), start=1):
        base = node_text(cell) or f"col_{index}"
        count = seen.get(base, 0) + 1
        seen[base] = count
        columns.append(base if count == 1 else f"{base}_{count}")
    return columns


def table_label(table_node: HtmlNode, owner: HtmlNode | None = None) -> str | None:
    for child in table_node.children:
        if child.tag == "caption":
            name = node_text(child)
            return name or None
    if owner is not None:
        for child in owner.children:
            if "caption" in (child.attrs.get("class") or "").split():
                label = node_text(child)
                return label or None
    return None


def table_owner_node(table_node: HtmlNode) -> HtmlNode | None:
    parent = table_node.parent
    while parent is not None:
        if parent.tag == "figure" and parent.attrs.get("data-type", "").lower() == "table":
            return parent
        parent = parent.parent
    return None


def is_table_overview_node(node: HtmlNode) -> bool:
    return (
        node.tag == "table"
        or (node.tag == "figure" and node.attrs.get("data-type", "").lower() == "table")
    )


def row_cells(row: HtmlNode) -> list[HtmlNode]:
    return [child for child in row.children if child.tag in {"th", "td"}]


def infer_element_type(tag: str) -> str:
    if tag == "h1":
        return "TITLE"
    if tag in {"h2", "h3", "h4", "h5", "h6"}:
        return "SECTION_HEADER"
    if tag == "li":
        return "LIST_ITEM"
    if tag == "table":
        return "TABLE"
    if tag == "caption":
        return "CAPTION"
    return "TEXT"


def infer_node_type(node: HtmlNode) -> str:
    if node.tag == "figure" and node.attrs.get("data-type", "").lower() == "table":
        return "TABLE"
    return infer_element_type(node.tag or "")


def heading_level(tag: str) -> int:
    return int(tag[1]) if tag in HEADING_TAGS else 99


def node_text(node: HtmlNode) -> str:
    parts: list[str] = []
    collect_text(node, parts)
    return " ".join("".join(parts).split())


def collect_text(node: HtmlNode, parts: list[str]) -> None:
    if node.tag is None:
        parts.append(node.text)
        return
    for child in node.children:
        collect_text(child, parts)


def walk(node: HtmlNode):
    yield node
    for child in node.children:
        yield from walk(child)


def _parent_id(node: HtmlNode) -> str | None:
    parent = node.parent
    while parent is not None:
        if parent.attrs.get("id"):
            return parent.attrs["id"]
        parent = parent.parent
    return None


__all__ = [
    "HtmlDocument",
    "HtmlElement",
    "HtmlTable",
    "build_html_document",
    "validate_required_ids",
    "build_elements_by_id",
    "build_document_tree",
    "build_tables_by_id",
    "parse_table",
    "extract_table_columns",
    "infer_element_type",
]
