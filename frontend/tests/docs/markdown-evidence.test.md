# markdown-evidence.test.tsx

这组测试覆盖 QA 对话里 Markdown 文本的结构化渲染，重点保证模型回答中的列表和 evidence 链接不会因为前端渲染器过于简化而变形。

实现链路：

```text
MarkdownEvidence(markdown)
  -> 把模型回答交给 Markdown 渲染器解析
  -> 将有序列表、无序列表和嵌套列表渲染为真实 ol/ul/li DOM
  -> 默认将 evidence:// Markdown link 渲染为可点击 a
  -> 如果 evidencePlacement=footer，先把正文 evidence link 替换成可读 label，再把引用集中渲染到末尾 Sources
  -> 点击 inline evidence 或 Sources citation 时阻止默认跳转并回调 onOpenEvidence(href, label)
```

## 测试函数

- `renders ordered list items with nested bullet details as one list`：验证 `1. ...` / `2. ...` 下带缩进 bullet 时，只生成一个连续 `<ol>`，且每个有序条目内部保留自己的 `<ul>` 明细，避免前端把每个编号段都重新渲染成 `1.`。
- `keeps evidence links clickable after markdown rendering`：验证普通 Markdown link 中的 `evidence://` 仍保留为可点击链接，并把 URI 和可见 label 传给 `onOpenEvidence`。
- `moves final answer evidence links into a sources footer`：验证最终回答模式会移除正文里的 evidence 链接点击态，只保留 label 文本，并在末尾 `Sources` 区生成可点击 citation。
- `renders a model-authored sources section as the unified footer`：验证模型已经输出 `Sources` 段时，前端会移除正文中的原始来源段，并用统一 footer 重渲染 citation，避免重复显示来源。
