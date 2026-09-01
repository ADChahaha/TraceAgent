# `test_mineru_html.py`

Tests conversion from MinerU `content_list_v2` pages to a single self-contained
HTML document (`build_html_from_content_list`).

实现步骤：

```text
MinerU pages
  -> 过滤 image/page_number/page_header/page_footer 这类不可用于推理的噪声
  -> title/paragraph/list/table 渲染成带 id 的 HTML（level2 开 section，level3 开 subsection）
  -> 保留两类轻量过滤：`目次` 页目录条目不进真章节；正文小标题（`1）`/`【..】`/
     `(..)` 括号编号/`<<>>`/单字母标号等）降级为普通正文行
  -> 其余 title 直接信任 MinerU 的 content.level 生成对应 heading（不再做层次聚类）
  -> 最终包一层 `<html><head><style>` CSS 壳，生成完整可渲染文档
```

测试覆盖：

- `test_build_html_from_content_list_preserves_ids_metadata_and_tables`：确认 HTML 是完整文档（含 `<style>`/`dp-evidence-highlight`），保留稳定 id、MinerU metadata、bbox、列表项和表格行 id，不暴露 MinerU 图片路径。
- `test_build_html_wraps_h2_and_h3_in_section_hierarchy`：确认 `h2` 打开语义 `<section>`，`h3` 打开 subsection，`h4` 及以下作为普通 block。
- `test_build_html_renders_body_subheadings_without_section_nodes`：确认 `1）` 这类正文小标题降级为普通段落，`3．出願手続` 这类真标题仍生成 section。
- `test_build_html_keeps_table_of_contents_entries_out_of_outline_headings`：确认 `目次` 页条目不生成 section，同名真实章节在正文页仍生成。
- `test_build_html_skips_pages_without_visible_content`：确认空页和纯图片页不会进入 HTML。
- `test_build_html_skips_pages_with_only_page_number`：确认纯页码页不会进入 HTML。
- `test_build_html_skips_page_footer_noise`：确认页脚版本号不会进入 HTML。
