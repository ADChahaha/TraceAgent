# Agent Context (handoff-ready)

> 最后更新：2026-04-16
> 目标：让任何新接入的 LLM/开发者在 2-5 分钟内理解当前 `agent/` 的状态并继续工作。

## 0) 项目总览

- 项目名：`agent_gate`
- 当前聚焦：`agent/` 服务的 OCR 预处理链路落地与稳定化，PDF 薄框 bbox 已做首轮图像精修，表格已升级为保留语义的 `table` blocks
- 主模块：`ocr_processor`（预处理/OCR）与 `file_extraction_agent`（抽取，待完善）
- 主链路：`raw file -> ocr_processor -> ProcessResult(blocks) -> file_extraction_agent`
- 当前支持：`pdf`、`docx`；`doc` 明确未实现
- PDF 默认模型路径：`agent/ocr_processor/impl/pdf/artifacts/docling-models`
- 当前状态：`ocr_processor` 关键用例可跑通，PDF `bbox` 可提取且已修正明显薄框，PDF 表格会输出 `kind="table"` + Markdown，`docx` 在 Docling 失败时可回退到 zip/xml 文本抽取

## 1) 当前目标与边界

`agent` 负责文档处理链路，分为两段：

- `ocr_processor`：文档预处理/OCR，输出统一 `ProcessResult(blocks)`
- `file_extraction_agent`：消费预处理结果做抽取（后续完善）

系统职责边界：

- `agent` 不直接查 backend DB，不直接管 backend storage
- 与 backend 通过 API 交互（任务输入/文件读取/结果回传）

## 2) 最近关键决策（已落地）

### PDF artifacts 路径归属

已确认并落地：PDF 的 Docling 本地模型目录按模块归属放在：

- `agent/ocr_processor/impl/pdf/artifacts/docling-models`

对应代码默认路径：

- `ocr_processor/impl/docling_adapter.py` 中 `_DEFAULT_DOCLING_ARTIFACTS_PATH`

对应文档已同步：

- `ocr_processor/README.md`

### 为什么这样改

- 只有 PDF 管线依赖这套 artifacts（DOCX 不依赖该本地模型目录）
- 放到 `impl/pdf` 下语义更清晰，避免顶层目录混乱

## 3) 当前处理行为（重点）

### 输入类型

- 支持：`pdf` / `doc` / `docx`
- 入口：`ocr_processor.processor.process(file_obj, file_type=None)`

### 输出结构

统一输出 `ProcessResult`，核心字段：

- `processor_name`
- `file_type`
- `filename`
- `blocks`（每块至少 `text/page_no/bbox/meta_info`）
- `meta_info`
- `warnings`

### PDF 处理链路

- 首选：Docling + RapidOCR（`meta_info["engine"] = "docling_rapidocr"`）
- 回退：pdfplumber（`meta_info["engine"] = "pdfplumber_fallback"`）
- 当 Docling 返回的高层文本框高度异常小时，会基于页面图像做一次局部 bbox 精修
- 如果本地 Docling artifacts 中包含 table structure 模型，则会开启表格结构分析，并把整表输出成 `kind="table"` block
- table block 的 `text` 直接使用 Markdown，`meta_info` 中会补 `row_count` / `column_count`
- 当前默认会压掉落在 table bbox 内的普通 text blocks，避免前端高亮时出现“整表大框 + 表内碎框”双重噪声

### DOC/DOCX 处理链路

- `docx`：默认 Docling；若 Docling 失败则回退到 zip/xml 文本抽取（text-only）
- `doc`：显式返回空 blocks + warning，`engine = "unimplemented"`

## 4) 测试状态（已验证）

在 `agent-gate` conda 环境下，`ocr_processor` 测试通过：

- 命令：`conda run -n agent-gate pytest tests/ocr_processor/test_processor.py -q`
- 结果：`6 passed`

新增 `docling_adapter` 单测：

- 命令：`conda run -n agent-gate pytest tests/ocr_processor/test_docling_adapter.py -q`
- 结果：`4 passed`

并且已验证 PDF 可产出 bbox（含扫描 PDF 场景）。

真实样本验证（2026-04-16）：

- 用户提供的 `实验报告-模板.docx` 会触发 Docling `SimplePipeline` 失败，但当前已能通过 zip/xml fallback 成功提取文本块
- 用户提供的扫描 PDF 第 1 页已成功输出 OCR blocks，并生成原页叠框图用于人工检查
- 当前发现问题：Docling 高层 `document.texts[*].prov.bbox` 在扫描 PDF 上常出现“高度接近 0 的细框”，直接用于高亮效果较差
- 当前进展：第 1 页“横线框”已明显改善；第 2 页表格页现已验证可输出单个 table block，并在原页叠框图中显示为整表红框
- 当前实测：`source-page-2.pdf` 处理结果为 `1` 个 table block + `38` 个表外 text blocks；表格 Markdown 已导出到 `agent/output/processor_checks/pdf-page-002-table-001.md`

## 5) 最近提交（与当前上下文相关）

- `ef12230` `fix(ocr): move docling artifacts path under impl/pdf`
- `e976b18` `docs(ocr): align README with current pdf artifacts layout`
- `ce96674` `test(agent): cover scanned pdf bbox extraction`
- `6857f1b` `test(agent): define legacy doc extraction behavior`
- `fdd9389` `feat(agent): support legacy doc extraction via textutil`
- `74a9671` `docs: sync agent context and TDD guidance`
- `28dd171` `test(agent): mark legacy doc as unimplemented again`
- `e9cc347` `fix(agent): revert legacy doc to explicit unimplemented`
- `981e119` `test(agent): define docx fallback on docling failure`
- `eea2f70` `fix(agent): add docx fallback for docling failures`
- `114bdf4` `test(agent): define pdf bbox image refinement behavior`
- `21fe8fb` `test(agent): define table block extraction behavior`

## 6) 当前工作区状态（需要注意）

仓库根目录当前有未提交内容：

- 修改：`agent/CONTEXT.md`
- 修改：`agent/ocr_processor/impl/docling_adapter.py`
- 修改：`agent/ocr_processor/impl/pdf/processor.py`
- 修改：`agent/ocr_processor/README.md`
- 未跟踪：`agent/output/`（真实样本验证输出）
- 未跟踪：`backend/`、`frontend/`

进行下一次提交时，建议只按目标文件精确 `git add`，避免误带无关改动。

## 7) 下一个建议动作（按优先级）

1. **继续清理非表格碎框**：对过小框、单字符噪声框或同一行碎片框做聚合/过滤。
2. **评估表格细粒度结构**：如果后续需要单元格级交互，可继续补 cell/row 级 bbox 映射。
3. **规划 legacy `.doc` 策略**：若要支持，优先选非平台专属的转换方案。

## 8) 快速上手命令

```bash
# 进入 agent
cd ./agent

# 运行 OCR 相关测试
conda run -n agent-gate pytest tests/ocr_processor/test_processor.py -q

# 查看当前改动
cd .
git status --short
```

## 9) 关键文件索引

- `ocr_processor/processor.py`：外部统一入口
- `ocr_processor/impl/dispatcher.py`：类型分发
- `ocr_processor/impl/pdf/processor.py`：PDF 处理 + fallback
- `ocr_processor/impl/doc/processor.py`：DOC/DOCX 处理
- `ocr_processor/impl/docling_adapter.py`：Docling 适配 + artifacts 路径
- `ocr_processor/README.md`：模块说明
- `tests/ocr_processor/test_processor.py`：核心测试
