"""Merge high-confidence continued HTML tables from Docling output."""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
from html.parser import HTMLParser


TABLE_CELL_TAGS = {"th", "td"}
STRUCTURAL_TABLE_TAGS = {"thead", "tbody", "tfoot"}
BLOCKING_TAGS = {
    "caption",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "p",
    "section",
    "article",
}


@dataclass(slots=True)
class HtmlNode:
    tag: str | None
    attrs: list[tuple[str, str]] = field(default_factory=list)
    children: list["HtmlNode"] = field(default_factory=list)
    text: str = ""


class HtmlTreeParser(HTMLParser):
    """Parse enough HTML to move table rows while preserving the rest."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = HtmlNode(tag=None)
        self._stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = HtmlNode(
            tag=tag.lower(),
            attrs=[(name.lower(), value or "") for name, value in attrs],
        )
        self._stack[-1].children.append(node)
        if tag.lower() not in {"br", "img", "meta", "link", "input"}:
            self._stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if data:
            self._stack[-1].children.append(HtmlNode(tag=None, text=data))


def merge_continued_tables(html: str) -> str:
    """Merge adjacent table fragments that look like one paginated table."""

    parser = HtmlTreeParser()
    parser.feed(html)
    parser.close()
    merge_continued_tables_in_children(parser.root.children)
    return "".join(serialize_node(child) for child in parser.root.children)


def merge_continued_tables_in_children(nodes: list[HtmlNode]) -> None:
    """Recursively merge continued tables within each sibling list."""

    index = 0
    while index < len(nodes):
        node = nodes[index]
        if node.tag is not None:
            merge_continued_tables_in_children(node.children)
        if node.tag != "table":
            index += 1
            continue

        next_table_index = find_next_table_index(nodes, index + 1)
        if next_table_index is None:
            index += 1
            continue

        current = nodes[next_table_index]
        between_nodes = nodes[index + 1 : next_table_index]
        if is_continued_table(node, current, between_nodes):
            append_continuation_rows(node, current)
            del nodes[next_table_index]
            continue
        index += 1


def find_next_table_index(nodes: list[HtmlNode], start: int) -> int | None:
    for index in range(start, len(nodes)):
        node = nodes[index]
        if node.tag == "table":
            return index
        if is_blocking_between_tables(node):
            return None
    return None


def is_continued_table(
    previous: HtmlNode,
    current: HtmlNode,
    between_nodes: list[HtmlNode],
) -> bool:
    """Return True when current table is very likely a continuation."""

    if any(is_blocking_between_tables(node) for node in between_nodes):
        return False

    previous_rows = extract_table_rows(previous)
    current_rows = extract_table_rows(current)
    if len(previous_rows) < 2 or not current_rows:
        return False

    previous_header = previous_rows[0]
    current_first = current_rows[0]
    previous_col_count = expanded_cell_count(previous_header)
    current_col_count = expanded_cell_count(current_first)
    if previous_col_count == 0 or previous_col_count != current_col_count:
        return False

    if not row_has_header_cells(previous_header):
        return False
    if not row_looks_like_data(current_first):
        return False
    if row_looks_like_header(current_first):
        return False

    return True


def append_continuation_rows(previous: HtmlNode, current: HtmlNode) -> None:
    """Append all rows from the continuation table to the previous table body."""

    target = table_row_container(previous)
    for row in extract_table_rows(current):
        convert_header_cells_to_data_cells(row)
        target.children.append(row)


def extract_table_rows(table: HtmlNode) -> list[HtmlNode]:
    rows: list[HtmlNode] = []
    for child in table.children:
        if child.tag == "tr":
            rows.append(child)
        elif child.tag in STRUCTURAL_TABLE_TAGS:
            rows.extend(node for node in child.children if node.tag == "tr")
    return rows


def table_row_container(table: HtmlNode) -> HtmlNode:
    for child in table.children:
        if child.tag == "tbody":
            return child
    return table


def expanded_cell_count(row: HtmlNode) -> int:
    count = 0
    for cell in row_cells(row):
        count += parse_positive_int(attr_value(cell, "colspan"), default=1)
    return count


def row_has_header_cells(row: HtmlNode) -> bool:
    return any(cell.tag == "th" for cell in row_cells(row))


def row_looks_like_header(row: HtmlNode) -> bool:
    cells = row_cells(row)
    if not cells:
        return False
    texts = [node_text(cell).strip() for cell in cells]
    non_empty = [text for text in texts if text]
    if not non_empty:
        return False
    if row_has_header_cells(row) and not row_looks_like_data(row):
        return True
    numeric_like = sum(looks_numeric(text) for text in non_empty)
    return numeric_like == 0 and len(non_empty) >= max(2, len(cells) // 2)


def row_looks_like_data(row: HtmlNode) -> bool:
    cells = row_cells(row)
    if not cells:
        return False
    texts = [node_text(cell).strip() for cell in cells]
    non_empty = [text for text in texts if text]
    if not non_empty:
        return False

    numeric_like = sum(looks_numeric(text) for text in non_empty)
    empty_count = len(texts) - len(non_empty)
    short_value_count = sum(0 < len(text) <= 8 for text in non_empty)
    return (
        numeric_like >= 1
        and short_value_count >= max(1, len(non_empty) - 1)
        and (numeric_like + empty_count) >= max(1, len(cells) // 2)
    )


def row_cells(row: HtmlNode) -> list[HtmlNode]:
    return [child for child in row.children if child.tag in TABLE_CELL_TAGS]


def convert_header_cells_to_data_cells(row: HtmlNode) -> None:
    for cell in row_cells(row):
        if cell.tag == "th":
            cell.tag = "td"


def is_blocking_between_tables(node: HtmlNode) -> bool:
    if node.tag is None:
        return bool(node.text.strip())
    if node.tag in {"br", "hr"}:
        return False
    if node.tag == "div" and not node_text(node).strip():
        return False
    if node.tag in BLOCKING_TAGS:
        return True
    return bool(node_text(node).strip())


def looks_numeric(text: str) -> bool:
    normalized = text.strip().replace(",", "")
    if not normalized:
        return False
    try:
        float(normalized)
    except ValueError:
        return any(char.isdigit() for char in normalized)
    return True


def attr_value(node: HtmlNode, name: str) -> str | None:
    for attr_name, value in node.attrs:
        if attr_name == name:
            return value
    return None


def parse_positive_int(value: str | None, *, default: int) -> int:
    try:
        parsed = int(value or "")
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def node_text(node: HtmlNode) -> str:
    if node.tag is None:
        return node.text
    return "".join(node_text(child) for child in node.children)


def serialize_node(node: HtmlNode) -> str:
    if node.tag is None:
        return escape(node.text, quote=False)
    attrs = "".join(
        f' {name}="{escape(value, quote=True)}"' for name, value in node.attrs
    )
    inner = "".join(serialize_node(child) for child in node.children)
    if node.tag in {"br", "hr", "img", "meta", "link", "input"}:
        return f"<{node.tag}{attrs}>"
    return f"<{node.tag}{attrs}>{inner}</{node.tag}>"

