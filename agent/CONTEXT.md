# Agent Context (handoff-ready)

> 最后更新：2026-04-16
> 目标：让任何新接入的 LLM/开发者在 2-5 分钟内理解当前 `agent/` 的状态并继续工作。

## 0) 项目总览

- 项目名：`agent_gate`
- 当前聚焦：`agent/` 服务的 OCR 预处理链路落地与稳定化，正在做真实 `PDF/DOCX` 样本验证
- 主模块：`ocr_processor`（预处理/OCR）与 `file_extraction_agent`（抽取，待完善）
- 主链路：`raw file -> ocr_processor -> ProcessResult(blocks) -> file_extraction_agent`
- 当前支持：`pdf`、`docx`；`doc` 明确未实现
- PDF 默认模型路径：`agent/ocr_processor/impl/pdf/artifacts/docling-models`
- 当前状态：`ocr_processor` 关键用例可跑通，PDF `bbox` 可提取，`docx` 在 Docling 失败时可回退到 zip/xml 文本抽取

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

### DOC/DOCX 处理链路

- `docx`：默认 Docling；若 Docling 失败则回退到 zip/xml 文本抽取（text-only）
- `doc`：显式返回空 blocks + warning，`engine = "unimplemented"`

## 4) 测试状态（已验证）

在 `agent-gate` conda 环境下，`ocr_processor` 测试通过：

- 命令：`conda run -n agent-gate pytest tests/ocr_processor/test_processor.py -q`
- 结果：`6 passed`

并且已验证 PDF 可产出 bbox（含扫描 PDF 场景）。

真实样本验证（2026-04-16）：

- 用户提供的 `实验报告-模板.docx` 会触发 Docling `SimplePipeline` 失败，但当前已能通过 zip/xml fallback 成功提取文本块
- 用户提供的扫描 PDF 第 1 页已成功输出 OCR blocks，并生成原页叠框图用于人工检查

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

## 6) 当前工作区状态（需要注意）

仓库根目录当前有未提交内容：

- 修改：`agent/CONTEXT.md`
- 修改：`agent/ocr_processor/README.md`
- 未跟踪：`agent/output/`（真实样本验证输出）
- 未跟踪：`backend/`、`frontend/`

进行下一次提交时，建议只按目标文件精确 `git add`，避免误带无关改动。

## 7) 下一个建议动作（按优先级）

1. **完成整本 PDF 可视化验证**：继续确认用户提供的 8 页扫描 PDF 每页叠框结果是否都合理。
2. **评估 fallback 粒度**：如果后续需要更强保真度，可继续补 header/footer/表格/文本框的抽取策略。
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
