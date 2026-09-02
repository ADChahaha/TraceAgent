"""Materialize semantic HTML documents into a real, on-disk file tree.

`DocumentFileTree` 是把上传的 HTML documents 落成一个真实目录树，每个
paragraph / list / table 都写成一个 `.md` 文件，供 `ls` / `grep`(rg) /
`read` 工具在真实文件系统上操作。没有 `path_id`、`evidence://` 或
`sentence/row selector`；引证就用真实文件路径。

实现步骤：

```text
documents(filename + html)
  -> 解析每个 HTML 生成 HtmlNode 树
  -> 按 h1-h6 层级建 section 目录，paragraph/list/table 各写一个 .md 文件
  -> 目录 / 文件用数字前缀保序（0001-xxx / 0002-xxx）
  -> DocumentFileTree.root / entries(path) / read(path) / scope_path(scope)
```

设计约定：

- 每个 document 是 `workspace_root/<completion_id>/0001-<doc>` 目录。
- section 是子目录；paragraph 是 `0001-xxx.md`，list 是 `0002-xxx.md`，
  table 是 `0003-xxx.md`（均写 markdown，表格整表一个文件）。
- list/table 不再有行级 selector，只保留一个文件作为证据单元。
- 排序靠文件名数字前缀，不靠 `os.listdir`。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from service.file_extraction_agent.schemas import InputDocument

HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
BLOCK_TAGS = {"p", "ul", "ol", "table"}
DEFAULT_SNIPPET_CHARS = 24


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
class FileEntry:
    name: str
    path: str
    kind: str
    order: int


@dataclass
class DocumentFileTree:
    root: Path

    def entries(self, path: str | None = None) -> list[FileEntry]:
        """List one level of the tree at a directory path, sorted by order.

        path may be a directory path (str) or None to use the tree root.
        Returns FileEntry with name/path/kind(order). kind is "dir" or "md".
        """

        directory = self._resolve_directory(path)
        entries: list[FileEntry] = []
        for child in sorted(directory.iterdir(), key=lambda p: _order_key(p.name)):
            if child.is_dir():
                entries.append(
                    FileEntry(name=child.name, path=str(child), kind="dir", order=_order_key(child.name))
                )
            elif child.is_file() and child.suffix == ".md":
                entries.append(
                    FileEntry(name=child.name, path=str(child), kind="md", order=_order_key(child.name))
                )
        return sorted(entries, key=lambda entry: entry.order)

    def read(self, path: str) -> str:
        """Read the markdown content of a file path as UTF-8 text."""

        resolved = self._resolve_file(path)
        return resolved.read_text(encoding="utf-8")

    def scope_path(self, scope: str | None = None) -> Path:
        """Resolve a model-facing scope to a directory under the tree root.

        Empty scope returns the root. Rejects `..` traversal outside the root.
        """

        if scope is None or not str(scope or "").strip():
            return self.root
        candidate = Path(str(scope)).resolve()
        root = self.root.resolve()
        if candidate == root:
            return root
        if root not in candidate.parents:
            raise ValueError("scope escapes the document workspace")
        if not candidate.exists() or not candidate.is_dir():
            raise ValueError(f"scope is not a directory: {scope}")
        return candidate

    def _resolve_directory(self, path: str | None) -> Path:
        if path is None or not str(path or "").strip():
            return self.root
        candidate = Path(str(path)).resolve()
        root = self.root.resolve()
        if candidate == root:
            return root
        if root not in candidate.parents:
            raise ValueError("path escapes the document workspace")
        if not candidate.exists() or not candidate.is_dir():
            raise ValueError(f"path is not a directory: {path}")
        return candidate

    def _resolve_file(self, path: str) -> Path:
        candidate = Path(str(path)).resolve()
        root = self.root.resolve()
        if root not in candidate.parents:
            raise ValueError("file escapes the document workspace")
        if not candidate.exists() or not candidate.is_file():
            raise ValueError(f"file not found: {path}")
        return candidate


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


def materialize_tree(documents: list[InputDocument], workspace_root: Path) -> DocumentFileTree:
    """Write documents to an on-disk file tree and return its accessor."""

    source_documents = normalize_documents(documents)
    root = Path(workspace_root)
    root.mkdir(parents=True, exist_ok=True)
    used_root_names: dict[str, int] = {}

    for document_index, source in enumerate(source_documents, start=1):
        parsed_root = parse_html(source.html)
        title_node = document_title_node(parsed_root)
        title = node_text(title_node) if title_node is not None else ""
        basename = slug_text(Path(source.filename).stem or "document")
        title_slug = slug_text(title) if title else ""
        base_name = f"{document_index:03d}-{basename}" + (f"-{title_slug}" if title_slug else "")
        doc_name = unique_name(base_name, used_root_names)
        doc_dir = root / doc_name
        doc_dir.mkdir(parents=True, exist_ok=True)
        write_document_children(doc_dir, parsed_root, document_index)

    return DocumentFileTree(root=root)


def normalize_documents(documents: list[InputDocument]) -> list[SourceDocument]:
    if not documents:
        raise ValueError("documents must be a non-empty list")
    normalized: list[SourceDocument] = []
    for index, document in enumerate(documents, start=1):
        if not document.filename.strip():
            raise ValueError(f"documents[{index}].filename is required")
        if not document.html.strip():
            raise ValueError(f"documents[{index}].html must be a non-empty string")
        normalized.append(SourceDocument(filename=document.filename.strip(), html=document.html))
    return normalized


def parse_html(html: str) -> HtmlNode:
    parser = _Parser()
    parser.feed(html)
    parser.close()
    return parser.root


def write_document_children(
    doc_dir: Path,
    parsed_root: HtmlNode,
    document_index: int,
) -> None:
    """Write section dirs and block .md files from the parsed HTML tree."""

    section_stack: list[tuple[int, Path]] = [(0, doc_dir)]
    sibling_counters: dict[Path, dict[str, int]] = {doc_dir: {}}

    for node in block_nodes(parsed_root):
        if node.tag in HEADING_TAGS:
            level = int(node.tag[1])
            while section_stack and section_stack[-1][0] >= level:
                section_stack.pop()
            parent_dir = section_stack[-1][1] if section_stack else doc_dir
            name = numbered_name(parent_dir, slug_text(node_text(node)) or "section", sibling_counters, suffix="")
            section_dir = parent_dir / name
            section_dir.mkdir(parents=True, exist_ok=True)
            sibling_counters[section_dir] = {}
            section_stack.append((level, section_dir))
            continue

        parent_dir = section_stack[-1][1] if section_stack else doc_dir
        if node.tag == "p":
            text = node_text(node)
            name = numbered_name(parent_dir, paragraph_slug(text), sibling_counters, suffix=".md")
            write_markdown_file(parent_dir / name, text)
        elif node.tag in {"ul", "ol"}:
            items = list_items(node)
            title = slug_text(items[0]["text"][:DEFAULT_SNIPPET_CHARS]) if items else "list"
            name = numbered_name(parent_dir, title or "list", sibling_counters, suffix=".md")
            write_markdown_file(parent_dir / name, render_list_markdown(items))
        elif node.tag == "table":
            table = parse_table(node)
            title = slug_text(table.get("label") or " ".join(table["columns"][:3]) or "table")
            name = numbered_name(parent_dir, title or "table", sibling_counters, suffix=".md")
            write_markdown_file(parent_dir / name, render_table_markdown(table))


def write_markdown_file(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


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
        if node.tag in {"h1", "title"}:
            if node_text(node):
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
    return {"label": label, "columns": columns, "rows": data_rows}


def render_list_markdown(items: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in items:
        indent = "  " * item["depth"]
        lines.append(f"{indent}- {item['text']}")
    return "\n".join(lines)


def render_table_markdown(table: dict[str, Any]) -> str:
    columns = table["columns"]
    rows = table["rows"]
    if not columns:
        return ""
    lines: list[str] = []
    if table.get("label"):
        lines.append(table["label"])
    lines.append("| " + " | ".join(columns) + " |")
    lines.append("| " + " | ".join("---" for _ in columns) + " |")
    for row in rows:
        padded = list(row) + [""] * (len(columns) - len(row))
        lines.append("| " + " | ".join(padded[: len(columns)]) + " |")
    return "\n".join(lines)


def numbered_name(parent: Path, slug: str, counters: dict[Path, dict[str, int]], *, suffix: str) -> str:
    bucket = counters.setdefault(parent, {})
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


def _order_key(name: str) -> int:
    digits = ""
    for char in name:
        if char.isdigit():
            digits += char
        else:
            break
    return int(digits) if digits else 0


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


def walk(node: HtmlNode):
    yield node
    for child in node.children:
        yield from walk(child)


__all__ = [
    "SourceDocument",
    "HtmlNode",
    "FileEntry",
    "DocumentFileTree",
    "materialize_tree",
]
