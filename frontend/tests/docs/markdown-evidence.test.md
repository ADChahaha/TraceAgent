# markdown-evidence.test.tsx

这组测试覆盖 QA 对话里 Markdown 文本的结构化渲染，重点保证模型回答中的列表和 evidence 链接不会因为前端渲染器过于简化而变形。

实现链路：

```text
MarkdownEvidence(markdown)
  -> 把模型回答交给 Markdown 渲染器解析
  -> 将有序列表、无序列表和嵌套列表渲染为真实 ol/ul/li DOM
  -> 默认将 evidence:// Markdown link 渲染为可点击 a
  -> 如果 evidencePlacement=citation，先移除模型可能追加在末尾的 Sources/References 区
  -> 最终回答正文里的每个 evidence link 保留在原句位置，但可见文本改成递增数字 marker
  -> 点击普通 inline evidence 或最终回答数字 citation 时阻止默认跳转并回调 onOpenEvidence(href, label)
```

## 测试函数

- `renders ordered list items with nested bullet details as one list`：验证 `1. ...` / `2. ...` 下带缩进 bullet 时，只生成一个连续 `<ol>`，且每个有序条目内部保留自己的 `<ul>` 明细，避免前端把每个编号段都重新渲染成 `1.`。
- `keeps evidence links clickable after markdown rendering`：验证普通 Markdown link 中的 `evidence://` 仍保留为可点击链接，并把 URI 和可见 label 传给 `onOpenEvidence`。
- `renders final answer evidence as inline numbered citations after sentences`：验证最终回答模式会把原正文里的 descriptive evidence label 换成句尾数字 marker，marker 仍保留原 href 并可打开 evidence。
- `strips model-authored trailing sources sections in final citation mode`：验证模型如果仍输出末尾 `Sources` 区，前端会在最终回答 citation 模式下移除它，避免重复引用区。
- `renders each bullet evidence as inline numbered citations`：验证连续 bullet 每一条自己的 evidence 都会留在该条 bullet 句尾并显示为递增数字 marker，不会另起引用行。
