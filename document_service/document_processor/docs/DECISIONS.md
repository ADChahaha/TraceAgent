# document_processor 关键决策

归属 [Document Processor 设计](DESIGN.md)，记录单文件文档解析模块的长期边界取舍。

## 1. 按格式拆分独立解析子包、统一文件对象单入口与精简返回契约

- 决定：`document_processor` 仅支持 PDF（`pdf/`）与 DOCX（`docx/`），对外只暴露唯一入口 `processor.process(file_obj, file_type=None)`，仅接收具备 `read()` 的 file-like 对象（支持 `seek()` 时读前后复位），不接收本地路径字符串；类型检测以显式规范化 `file_type` 优先，缺失时再按文件名后缀判断；`ProcessResult` 仅保留 `filename` 与 `html` 两个字段，不抽取业务字段，不暴露独立网络入口，不负责资源发布，不保留 `BaseDocumentProcessor` / `impl/` 注册抽象。
- 原因：上游经内存 `BytesIO` 传入字节流可避免额外落盘；显式 `file_type` 优先可防止无文件名或后缀不准导致误判；两类格式管线差异大且固定单一实现，保持独立子包与精简返回契约既避免无意义抽象，又便于后续按"面向增加"扩展新格式。
- 排除：按格式拆分对外接口或独立 HTTP 端点；要求调用方传本地路径；保留抽象基类与注册表层；维护 `blocks`/`markdown`/`md_list` 等冗余输出字段，或在解析层耦合字段抽取与存储发布。

## 2. PDF 统一走 MinerU 单一管线，失败 fail-fast，不做双轨或静默回退

- 决定：所有 PDF（无论是否自带原生文本层）统一走 MinerU CLI 管线（`mineru -b pipeline -m auto -l <lang> -f false -t true`，锁定 `mineru[core]==3.1.6`）产出 `content_list_v2.json` 后转 HTML；MinerU 缺失、退出非零或未产出有效列表时直接抛 `MinerUConversionError`，禁止静默降级到其他解析库。
- 原因：需同时兼容无文本层扫描件与复杂多栏表格；实测表明静默回退 `pdfplumber` 会打碎表格并掩盖环境故障，`OcrMac` 绑定 macOS 且实测漏字严重，`Marker`/`Surya` 6 页耗时约 482 秒无法同步交互，`PPStructureV3` 复杂表格列序错乱，`RapidOCR` 误识与英文空格粘连明显，`Dedoc` 依赖本机未装的 Java 且混入目录列表，`Docling` 标题层级统一标为 level=1 依赖沉重（`docling-hierarchical-pdf` 易误升编号列表），`PyMuPDF4LLM` 部分页面触发乱码，MinerU `vlm-http-client` 与通用聊天模型协议不兼容。
- 排除：文本层 PDF 与扫描件走双轨分支（含单独切 `-m txt`）；以 Docling、Dedoc、PyMuPDF4LLM、Marker/Surya、PaddleOCR/PPStructureV3、RapidOCR、OcrMac、OpenCV 表格重建或通用 VLM 替代 MinerU；失败时静默回退弱解析器。

## 3. MinerU HTML 采用三级容器与块级证据，信任 `content.level` 加轻量降级

- 决定：基于 `content_list_v2.json` 生成带 CSS 的完整 HTML，`level=2`/`level=3` 生成 `<section>` 与 `<h2>`/`<h3>`，`level>=4` 降级为无加粗普通 `<p>`；直接信任 MinerU `content.level` 并仅保留目次页与正文短小标题轻量降级（HTML 阶段即输出无 `<strong>` 的 `<p>`），不硬编码跨文档编号族上下级顺序，弃用版面几何聚类；过滤页眉、页码、页脚、纯图、公式、空页及表格 `image_source` 路径，跳过空页保持原页码 `page_xxx` 与 `pXXX_bYYY` 不重排；表格仅对 `<table>` 与 `<tr>` 注入确定性 ID，不给 `<td>`/`<th>` 加 ID，不做行列修补或跨页续表合并。
- 原因：下游直接按 HTML `h1`-`h6` 建树，须在 HTML 阶段完成无加粗降级；保留原页码可与原 PDF 页数对齐；MinerU 输出不含字体/字号/加粗元数据，无监督几何聚类在小样本与多版式下脆弱；猜测修补表格行列易破坏原始 OCR 结构。
- 排除：保留 `h4+` 章节或 `<p><strong>` 降级标题；过滤空页后重排页码；给单元格加 ID 或猜测修补表格行列；恢复 KMeans/HDBSCAN 几何聚类或硬编码编号层级顺序。

## 4. DOCX 固定纯 `python-docx` 按显式 Heading 样式建树，不支持 `.doc`

- 决定：DOCX 固定使用 `python-docx` 按 `document.element.body` 原始顺序遍历段落与表格，仅依据显式 Word 标题样式（`Heading N` / `标题 N` / `見出し N`，1 至 9 级）生成嵌套 `<section>` 与 `<hN>`，无标题样式时保持扁平输出，不靠字号/加粗猜标题；明确不支持旧版二进制 `.doc`。
- 原因：实测 Docling 解析含 DrawingML 文本框的 DOCX 会调用本机 LibreOffice 触发崩溃并引入桌面软件强依赖；不猜标题可避免排版随意文档被误切章节；支持 `.doc` 会引入 `textutil` 平台绑定或 LibreOffice 风险。
- 排除：用 Docling 或 LibreOffice 转换解析 DOCX/`.doc`；按字号、加粗或样本文本启发式猜标题。

## 5. 解析算法实验隔离在 `experiments/`，集成测试动态合成样本

- 决定：所有探索性解析或标题层级算法实验必须隔离在已忽略的根目录 `experiments/`，严禁写入生产转换代码；公开仓库不提交真实业务 PDF/DOCX、解析产物或大体积演示视频，`document_processor` 集成测试在 `tmp_path` 动态合成最小 `%PDF` 与内存构建 `.docx`。
- 原因：防止实验代码污染主解析链路，并规避公开仓库分发真实业务文档的隐私风险。
- 排除：在生产模块中直接写实验分支；将真实业务文档或脱敏静态 PDF/DOCX 提交进公开仓库 fixture。
