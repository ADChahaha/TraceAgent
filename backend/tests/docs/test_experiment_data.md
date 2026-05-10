# test_experiment_data.py

这份测试覆盖后端内置实验数据接口。测试目标是确认 ContractNLI 实验结果已经由 backend 提供，前端不需要直接读取 `experiments/` 目录。

## 测试链路

```text
TestClient 请求 /experiments/contract-nli
  -> backend 返回 ContractNLI dev_all 摘要、样本列表和默认样本 id
  -> TestClient 请求 /experiments/contract-nli/samples/{sample_id}/detail
  -> backend 优先使用已缓存的 PDF OCR trace，否则使用内置 agent trace
  -> backend 组装成前端可复用的 TaskDetailData 形状
  -> 测试确认 replay 中包含 search_elements action 和 display_html
  -> TestClient 请求 /experiments/contract-nli/samples/{sample_id}/html-process
  -> backend 返回 raw HTML、规范化 agent HTML、元素数和关键词命中
```

## 测试函数

- `test_contract_nli_experiment_summary_and_sample_detail_are_served_from_backend`：确认 backend 暴露 ContractNLI 实验摘要，且默认样本 detail 包含 `result.fields`、`replay.actions`、`search_elements` 动作和可展示的 HTML。
- `test_contract_nli_html_process_shows_raw_and_agent_html`：确认 backend 能为 `sec-html` 样本返回原始 HTML 片段、规范化后的 agent HTML 片段、元素数量和关键词命中统计，让前端可以展示 HTML 输入转换过程。
- `test_contract_nli_html_process_uses_cached_pdf_ocr_html`：确认 backend 能为已跑过 OCR 的 PDF 样本返回 MinerU 产出的完整 agent/display HTML、OCR block 数和关键词命中统计，让前端可以查看 PDF 进入 agent 前的真实块级 HTML。
- `test_contract_nli_pdf_detail_uses_ocr_trace_evidence_ids`：确认已跑过 OCR 的 PDF 样本 detail 会优先使用 OCR run 的 trace，避免前端把 OCR HTML 和旧 dev_all trace 混用，导致 evidence id 全部落到 header。
