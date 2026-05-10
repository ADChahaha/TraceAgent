# `contract-nli-experiment.test.tsx`

这份测试覆盖 ContractNLI 实验页。测试目标是确认前端从 backend 读取内置实验数据后，能把 `search_elements` 动作渲染成和其他 replay 动作一致的可读卡片。

## 测试链路

```text
ContractNliExperiment 挂载
  -> 调用 getContractNliExperiment 读取报告和样本列表
  -> 自动加载默认样本 detail
  -> 自动加载默认样本 html-process
  -> 展示 raw HTML / agent HTML 转换过程和关键词命中统计
  -> 如果 html-process 带有完整 OCR/display HTML，用它覆盖 replay 文档 HTML，并从 OCR block 生成文档 overview
  -> ReplayReview 渲染 search_elements 动作卡、样本按钮和 replay 文档
```

## 测试函数

- `从 backend 读取 ContractNLI 实验并渲染 search_elements trace`：确认实验页能读到 backend 的 ContractNLI 摘要，默认样本会自动展开，`HTML 输入过程` 面板会展示 raw/agent 元素数和关键词命中，且 `search_elements` 动作会以可读卡片形式展示 query 和命中片段。
- `PDF OCR 样本把 OCR HTML 传给 replay 文档视图`：确认 PDF OCR 样本不只在 `HTML 输入过程` 面板展示 OCR HTML，也会把完整 OCR/display HTML 传给 `ReplayReview` 的 iframe 文档视图，并让 `文档 Overview` 出现正文 block，避免 replay 里仍然只有旧的单个标题节点。
