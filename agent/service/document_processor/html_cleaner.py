"""清理 docling HTML 的页面壳和装饰属性。

实现步骤：

```text
docling raw html
  -> HTMLParser 解析出节点树
  -> 丢弃 head/style/script/meta 等页面壳
  -> 展开 html/body
  -> 其他标签按 docling 输出原样保留
  -> 属性只保留 id/rowspan/colspan
  -> 为缺少 id 的段落、列表、表格、表格行等块级节点补稳定 id
  -> 输出 HTML fragment
```
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
from html.parser import HTMLParser


ROOT_TAGS = {"html", "body"}
SKIPPED_WITH_CONTENT_TAGS = {"head", "style", "script", "noscript"}
SKIPPED_EMPTY_TAGS = {"meta", "link"}
TABLE_CELL_TAGS = {"th", "td"}
ID_TAGS = {
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "p",
    "ul",
    "ol",
    "li",
    "table",
    "tr",
    "caption",
}


@dataclass(slots=True)
class HtmlNode:
    tag: str | None
    attrs: dict[str, str] = field(default_factory=dict)
    children: list["HtmlNode"] = field(default_factory=list)
    text: str = ""


class HtmlFragmentParser(HTMLParser):
    """把 HTML 解析成轻量节点树，供清理属性和页面壳使用。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = HtmlNode(tag=None)
        self._stack = [self.root]
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in SKIPPED_WITH_CONTENT_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth or tag in SKIPPED_EMPTY_TAGS:
            return

        node = HtmlNode(tag=tag, attrs=_attrs_to_dict(attrs))
        self._stack[-1].children.append(node)
        if tag != "br":
            self._stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in SKIPPED_WITH_CONTENT_TAGS:
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if self._skip_depth or tag == "br":
            return

        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if self._skip_depth or not data:
            return
        self._stack[-1].children.append(HtmlNode(tag=None, text=data))


def clean_semantic_html(html: str, *, id_prefix: str = "dp") -> str:
    """删除页面壳和装饰属性，返回 HTML fragment。"""

    parser = HtmlFragmentParser()
    parser.feed(html)
    parser.close()

    nodes = clean_children(parser.root.children)
    assign_ids(nodes, prefix=id_prefix)
    return serialize_fragment(nodes)


def clean_children(nodes: list[HtmlNode]) -> list[HtmlNode]:
    """递归清理一组节点。"""

    cleaned: list[HtmlNode] = []
    for node in nodes:
        cleaned.extend(clean_node(node))
    return cleaned


def clean_node(node: HtmlNode) -> list[HtmlNode]:
    """清理单个节点，html/body 只展开不保留。"""

    if node.tag is None:
        return [HtmlNode(tag=None, text=" ".join(node.text.split()))] if node.text.strip() else []

    tag = node.tag.lower()
    children = clean_children(node.children)
    if tag in ROOT_TAGS:
        return children

    return [
        HtmlNode(
            tag=tag,
            attrs=clean_attrs(tag, node.attrs),
            children=children,
        )
    ]


def clean_attrs(tag: str, attrs: dict[str, str]) -> dict[str, str]:
    """只保留抽取需要的结构属性。"""

    cleaned: dict[str, str] = {}
    if attrs.get("id"):
        cleaned["id"] = attrs["id"]
    if tag in TABLE_CELL_TAGS:
        for attr_name in ("rowspan", "colspan"):
            value = attrs.get(attr_name)
            if value:
                cleaned[attr_name] = value
    return cleaned


def assign_ids(nodes: list[HtmlNode], *, prefix: str) -> None:
    """为缺少 id 的关键节点补稳定 id。"""

    counters: dict[str, int] = {}
    existing_ids = {
        node.attrs["id"]
        for node in walk_nodes(nodes)
        if node.tag is not None and node.attrs.get("id")
    }
    for node in walk_nodes(nodes):
        if node.tag is None or node.tag == "br" or node.attrs.get("id"):
            continue
        id_name = id_counter_name(node.tag)
        if node.tag in ID_TAGS:
            node.attrs["id"] = next_generated_id(
                prefix=prefix,
                id_name=id_name,
                counters=counters,
                existing_ids=existing_ids,
            )


def next_generated_id(
    *,
    prefix: str,
    id_name: str,
    counters: dict[str, int],
    existing_ids: set[str],
) -> str:
    """生成不和源 HTML 既有 id 冲突的稳定 id。"""

    while True:
        counters[id_name] = counters.get(id_name, 0) + 1
        candidate = f"{prefix}-{id_name}-{counters[id_name]}"
        if candidate not in existing_ids:
            existing_ids.add(candidate)
            return candidate


def walk_nodes(nodes: list[HtmlNode]):
    """按文档顺序遍历所有节点。"""

    for node in nodes:
        yield node
        yield from walk_nodes(node.children)


def id_counter_name(tag: str) -> str:
    """返回 id 计数使用的语义名。"""

    return tag


def serialize_fragment(nodes: list[HtmlNode]) -> str:
    """把清理后的节点序列化为 HTML fragment。"""

    return "\n".join(serialize_node(node) for node in nodes)


def serialize_node(node: HtmlNode) -> str:
    """序列化单个清理后的节点。"""

    if node.tag is None:
        return escape(node.text, quote=False)
    if node.tag == "br":
        return "<br>"

    attrs = serialize_attrs(node.attrs)
    inner_html = "".join(serialize_node(child) for child in node.children)
    return f"<{node.tag}{attrs}>{inner_html}</{node.tag}>"


def serialize_attrs(attrs: dict[str, str]) -> str:
    """序列化保留下来的安全属性。"""

    if not attrs:
        return ""
    return "".join(
        f' {name}="{escape(value, quote=True)}"' for name, value in attrs.items()
    )


def _attrs_to_dict(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
    return {name.lower(): value for name, value in attrs if value is not None}
