# markdown-evidence.test.tsx

这组测试覆盖 QA 对话里 Markdown 文本的结构化渲染，重点保证模型回答中的列表和 evidence 链接不会因为前端渲染器过于简化而变形。

实现链路：

```text
MarkdownEvidence(markdown)
  -> 把模型回答交给 Markdown 渲染器解析
  -> 将有序列表、无序列表和嵌套列表渲染为真实 ol/ul/li DOM
  -> 将 evidence:// Markdown link 渲染为可点击 a
  -> 点击 evidence link 时阻止默认跳转并回调 onOpenEvidence(href, label)
```

## 测试函数

- `renders ordered list items with nested bullet details as one list`：验证 `1. ...` / `2. ...` 下带缩进 bullet 时，只生成一个连续 `<ol>`，且每个有序条目内部保留自己的 `<ul>` 明细，避免前端把每个编号段都重新渲染成 `1.`。
- `keeps evidence links clickable after markdown rendering`：验证普通 Markdown link 中的 `evidence://` 仍保留为可点击链接，并把 URI 和可见 label 传给 `onOpenEvidence`。
