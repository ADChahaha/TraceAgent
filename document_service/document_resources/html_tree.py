"""HTML DOM 解析、列表/表格抽取与 Markdown 渲染辅助。"""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
BLOCK_TAGS = {"p", "ul", "ol", "table"}


@dataclass
class HtmlNode:
    tag: str | None
    attrs: dict[str, str] = field(default_factory=dict)
    children: list["HtmlNode"] = field(default_factory=list)
    text: str = ""
    parent: "HtmlNode | None" = None


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


def parse_html(html: str) -> HtmlNode:
    parser = _Parser()
    parser.feed(html)
    parser.close()
    return parser.root


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


def document_title_node(root: HtmlNode) -> HtmlNode | None:
    for node in walk(root):
        if node.tag in {"h1", "title"} and node_text(node):
            return node
    return None


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
    """HTML 行与单元格 -> 按跨度填充逻辑网格 -> 首行列名及其余数据行。"""
    label = ""
    rows: list[list[str]] = []
    occupied: dict[tuple[int, int], str] = {}
    row_index = 0
    for child in walk(node):
        if child.tag == "caption" and not label:
            label = node_text(child)
        if child.tag == "tr":
            column = 0
            for cell in (item for item in child.children if item.tag in {"th", "td"}):
                while (row_index, column) in occupied:
                    column += 1
                colspan = _cell_span(cell, "colspan")
                rowspan = _cell_span(cell, "rowspan")
                for dy in range(rowspan):
                    for dx in range(colspan):
                        occupied[row_index + dy, column + dx] = node_text(cell)
                column += colspan
            width = max((col + 1 for row, col in occupied if row == row_index), default=0)
            if width:
                rows.append([occupied.get((row_index, col), "") for col in range(width)])
            row_index += 1
    columns = rows[0] if rows else []
    data_rows = rows[1:] if rows else []
    return {"label": label, "columns": columns, "rows": data_rows}


def _cell_span(cell: HtmlNode, attr: str) -> int:
    try:
        return max(1, min(int(cell.attrs.get(attr, "1")), 1000))
    except ValueError:
        return 1


def render_list_markdown(items: list[dict[str, Any]]) -> str:
    return "\n".join(f"{'  ' * item['depth']}- {item['text']}" for item in items)


def render_table_markdown(table: dict[str, Any]) -> str:
    columns = table["columns"]
    rows = table["rows"]
    if not columns:
        return ""
    width = max(map(len, [columns, *rows]))

    def render_row(row: list[str]) -> str:
        cells = list(row) + [""] * (width - len(row))
        return "| " + " | ".join(cell.replace("|", "\\|") for cell in cells) + " |"

    lines: list[str] = []
    if table.get("label"):
        lines.append(table["label"])
    lines.append(render_row(columns))
    lines.append(render_row(["---"] * width))
    for row in rows:
        lines.append(render_row(row))
    return "\n".join(lines)


def node_text(node: HtmlNode) -> str:
    if node.tag is None:
        return " ".join(node.text.split())
    return " ".join(part for part in (node_text(child) for child in node.children) if part).strip()


def walk(node: HtmlNode):
    yield node
    for child in node.children:
        yield from walk(child)
