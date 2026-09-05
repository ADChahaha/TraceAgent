from __future__ import annotations

from pathlib import Path

import pytest

from service.document_resources.documents import materialize_tree
from service.file_extraction_agent.core.tools.workspace import DocumentFileTree
from service.document_resources.schemas import InputDocument


@pytest.mark.parametrize("html, expected", [
    ('<table><tr><th colspan="2">费用</th></tr><tr><td>服务A</td><td>100</td></tr></table>', ['| 费用 | 费用 |', '| 服务A | 100 |']),
    ('<table><tr><th>项目</th><th>金额</th></tr><tr><td rowspan="2">服务A</td><td>100</td></tr><tr><td>200</td></tr></table>', ['| 服务A | 100 |', '| 服务A | 200 |']),
    ('<table><tr><th>项目</th></tr><tr><td>A|B</td><td>100</td></tr></table>', ['| A\\|B | 100 |']),
])
def test_table_preserves_merged_cells_and_wider_rows(tmp_path, html, expected):
    DocumentFileTree(materialize_tree([InputDocument(filename="fees.html", html=html)], tmp_path))
    rendered = next(tmp_path.rglob("*.md")).read_text(encoding="utf-8")
    for row in expected:
        assert row in rendered


def _documents():
    return [
        InputDocument(
            filename="contract.html",
            html="""
            <h1 id="t1">项目设计说明</h1>
            <h2 id="h1">背景</h2>
            <p id="p1">这个项目最初是为了抽取字段。</p>
            <p id="p2">这个项目最初是为了验证重名段落。</p>
            <h2 id="h2">背景</h2>
            <ul id="l1">
              <li id="li1">第一项</li>
              <li id="li2">第二项<ul id="l2"><li id="li3">子项</li></ul></li>
            </ul>
            <h1 id="t1b">补充说明</h1>
            <p id="p1b">补充说明正文。</p>
            <table id="tbl1">
              <caption id="cap1">费用明细</caption>
              <tr id="tr0"><th>项目</th><th>金额</th></tr>
              <tr id="tr1"><td>服务费</td><td>1000</td></tr>
              <tr id="tr2"><td>押金</td><td>500</td></tr>
            </table>
            """,
        ),
        InputDocument(
            filename="contract.html",
            html="""
            <h1 id="t2">项目设计说明</h1>
            <h2 id="h3">摘要</h2>
            <p id="p3">第二个文件。</p>
            """,
        ),
    ]


def test_materialize_tree_writes_real_files_for_multiple_documents(tmp_path):
    tree = DocumentFileTree(materialize_tree(_documents(), tmp_path))

    assert tree.root == tmp_path
    assert tree.root.is_dir()
    doc_dirs = [entry for entry in tree.entries() if entry.kind == "dir"]
    assert [entry.name for entry in doc_dirs] == [
        "001-contract-项目设计说明",
        "002-contract-项目设计说明",
    ]
    assert [entry.path for entry in doc_dirs] == [
        str(tmp_path / "001-contract-项目设计说明"),
        str(tmp_path / "002-contract-项目设计说明"),
    ]


def test_tree_entries_respect_depth_and_file_kinds(tmp_path):
    tree = DocumentFileTree(materialize_tree(_documents(), tmp_path))

    root_entries = tree.entries()
    assert [e.name for e in root_entries] == [
        "001-contract-项目设计说明",
        "002-contract-项目设计说明",
    ]

    doc_entries = tree.entries(str(tmp_path / "001-contract-项目设计说明"))
    assert [e.name for e in doc_entries] == [
        "001-项目设计说明",
        "002-补充说明",
    ]
    assert [e.kind for e in doc_entries] == ["dir", "dir"]


def test_tree_writes_paragraph_list_and_table_as_markdown_files(tmp_path):
    tree = DocumentFileTree(materialize_tree(_documents(), tmp_path))

    section = tree.entries(str(tmp_path / "001-contract-项目设计说明" / "001-项目设计说明"))
    names = [e.name for e in section]
    assert names == [
        "001-背景",
        "002-背景",
    ]

    first_section = tree.entries(str(tmp_path / "001-contract-项目设计说明" / "001-项目设计说明" / "001-背景"))
    assert [e.name for e in first_section] == [
        "001-这个项目最初是为了抽取字段.md",
        "002-这个项目最初是为了验证重名段落.md",
    ]
    assert [e.kind for e in first_section] == ["md", "md"]

    read = tree.read(str(tmp_path / "001-contract-项目设计说明" / "001-项目设计说明" / "001-背景" / "001-这个项目最初是为了抽取字段.md"))
    assert read == "这个项目最初是为了抽取字段。"


def test_tree_writes_list_with_nested_markdown(tmp_path):
    tree = DocumentFileTree(materialize_tree(_documents(), tmp_path))

    list_file = tmp_path / "001-contract-项目设计说明" / "001-项目设计说明" / "002-背景" / "001-第一项.md"
    content = tree.read(str(list_file))

    assert "- 第一项" in content
    assert "- 第二项 子项" in content
    assert "  - 子项" in content


def test_tree_writes_table_as_one_markdown_file(tmp_path):
    tree = DocumentFileTree(materialize_tree(_documents(), tmp_path))

    table_file = tmp_path / "001-contract-项目设计说明" / "002-补充说明" / "002-费用明细.md"
    content = tree.read(str(table_file))

    assert "费用明细" in content
    assert "| 项目 | 金额 |" in content
    assert "| 服务费 | 1000 |" in content


def test_tree_orders_entries_by_numeric_prefix_not_filesystem(tmp_path):
    tree = DocumentFileTree(materialize_tree(
        [
            InputDocument(
                filename="letters.html",
                html='<h1>Letters</h1><p id="p1">Beta paragraph.</p><p id="p2">Alpha paragraph.</p>',
            )
        ],
        tmp_path,
    ))

    section = tree.entries(str(tmp_path / "001-letters-Letters" / "001-Letters"))
    names = [e.name for e in section]

    assert names == [
        "001-Beta paragraph.md",
        "002-Alpha paragraph.md",
    ]


def test_tree_read_rejects_paths_outside_workspace(tmp_path):
    tree = DocumentFileTree(materialize_tree([InputDocument(filename="a.html", html="<p>text</p>")], tmp_path))

    with pytest.raises(ValueError):
        tree.read(str(tmp_path.parent / "outside.md"))


def test_tree_entries_reject_paths_outside_workspace(tmp_path):
    tree = DocumentFileTree(materialize_tree([InputDocument(filename="a.html", html="<p>text</p>")], tmp_path))

    with pytest.raises(ValueError):
        tree.entries(str(tmp_path.parent))


def test_materialize_tree_rejects_document_without_filename_or_html(tmp_path):
    with pytest.raises(ValueError, match="filename"):
        DocumentFileTree(materialize_tree([InputDocument(filename="", html="<p>x</p>")], tmp_path))
    with pytest.raises(ValueError, match="html"):
        DocumentFileTree(materialize_tree([InputDocument(filename="a.html", html="")], tmp_path))
