# 执行计划: `config.toml` 配置重构、模型总结会话标题与 TraceAgent 前端重设计

状态: 已完成 (2026-11-25)

## 目标与范围

将本次拍板的三项改造拆分为三个独立、可逐阶段验收与提交的变更，不破坏 [ARCHITECTURE.md](../../../ARCHITECTURE.md) 单向依赖分层与核心不变量:

1. **Phase 1: 全仓配置从 `.env` 切换为 `config.toml`**
   - 根目录提供 `config.example.toml` 模板与本地忽略的 `config.toml`（支持环境变量 `TRACEAGENT_CONFIG` 指定路径）。
   - 在 `shared/traceagent_shared/config.py` 新增基于 Python 3.11 标准库 `tomllib` 的统一配置读取模块与 shell 导出 CLI，不新增第三方依赖。
   - 移除运行态对 `.env` 文件的读取（保留显式进程环境变量对 `config.toml` 的覆盖能力，方便测试、CLI 参数与容器注入）。
   - `scripts/start.sh`、`agent`、`document_service`、`backend`、`storage`、`shared` 与 `.github/workflows/ci.yml` 统一接入 `config.toml`；将本机现有 `.env` 键值无损迁入本机 `config.toml`。

2. **Phase 2: 模型总结会话标题 (告别 UUID)**
   - 严守 `backend` 不做模型推理的分层边界: 在 [agent.proto](../../../agent_proto/agent.proto) 的 `AgentService` 新增轻量无状态 `GenerateTitle(GenerateTitleRequest) returns (GenerateTitleResponse)` RPC 并重新生成绑定。
   - 在 `agent` 新增独立标题生成模块，复用 `config.toml` 的 `[title_model]`（未配时回退 `[model]`），按用户提问语言生成简洁标题（无引号与 Markdown 装饰，截断安全长度）。
   - 在 `backend` 的 `chat_sessions` 表新增可空 `title TEXT` 列（启动初始化自动对已有旧库幂等执行 `ALTER TABLE ADD COLUMN`），首轮提交后异步并发触发标题生成（不阻塞问答 SSE 流），落库后推送轻量会话更新事件；失败或超时静默降级为首条问题/首个文件名摘要，绝不影响主问答。
   - `GET /chat/sessions` 与 `GET /chat/sessions/{id}/resume` 快照返回 `title` 字段；无标题的旧会话由接口兜底派生首条用户问题或首个文件名（仍空则回退 `Untitled workspace`），绝不展示 UUID。

3. **Phase 3: TraceAgent 前端视觉与排版重设计**
   - 品牌统一: 顶栏、首页、浏览器页签元数据从 `Agent Gate` 统一改为 `TraceAgent`。
   - 色彩与双主题: 对齐实测 Antigravity / Codex 中性色阶。
     - Light 模式: 左侧原始文档面与文件栏 `#FAFAFA`，1px 分割线 `#E6E6E6`，右侧 Agent 对话面纯白 `#FFFFFF`，用户气泡纯白 `#FFFFFF` 配 `#EBEBEB` 细边与微投影，发送钮、激活引用与原文高亮统一使用沉静钢蓝 `#3978C8`。
     - Dark 模式: 顶栏 `#141414`，左文件列表 `#141414`，右侧 Agent 对话面纯中性炭黑 `#181818`，浮起输入框与用户气泡 `#222222`，主蓝 `#4E8EE0`；**左侧打开的原始文档纸面恒定保持 `#FAFAFA` 白纸黑字**（外围仅 6-10px 极细暗槽）。
   - 排版与去噪:
     - 顶栏收敛为 44px 极简图标栏，删除会话页冗余的 `Document conversation` 副顶栏。
     - 首页改为单聚焦居中舞台，取消左侧空栏与 `Get a summary` / `Explore the details` 快捷卡片，仅保留 `TraceAgent`、一体化输入框、回形针附件入口与行内文件状态。
     - 左侧文件栏与原文阅读器大幅图标化去冗余文字（删重复 `DOCX` 标签与 `Click to read` 文本，保留下载/删除图标、搜索框与 `+` 补传入口）。
     - 右侧 Agent 检索过程收紧为低存在感可展开折叠行（保留稳定 key 与失败工具中性配色）；最近会话抽屉展示可读会话标题。
   - 高亮、滚动与分栏修复:
     - 原文引用高亮采用**柔光块**（`rgba(57, 120, 200, 0.13)` + 左侧贴边 3px 钢蓝直竖条，右侧圆角左侧平直，无弯钩）。
     - 修复 [source-reader.tsx](../../../frontend/src/components/session/source-reader.tsx) 使用 `scrollIntoView({ block: "center" })` 导致整页上下拉扯的问题: 改为仅操作左侧文档滚动容器的 `scrollTo`，且目标段已在可视范围内时不重复拉扯。
     - 放宽 [sidebar-resize.tsx](../../../frontend/src/components/sidebar-resize.tsx) 左栏可拖拽范围（默认约对半展开，允许用户自由拖拽）；点击任意引用或切换文件列表绝不强制重置左右宽度。
   - 文案门禁: 图标化后保留的少量占位符、错误提示、状态与无障碍标签统一使用英文，继续通过 [frontend-copy.test.ts](../../../frontend/tests/frontend-copy.test.ts)。

## 非目标

- 不引入外部配置中心或复杂多环境继承系统，只支持单份 `config.toml` 加进程环境变量覆盖。
- 不做手动重命名会话标题或删除会话的新 HTTP 接口（若后续需要可单独增加）。
- 不修改现有问答 Agent 的工具循环逻辑、`document_service` 解析策略或取消协议。

## 验收标准

### Phase 1 (`config.toml`)
1. 仓库根目录存在无密钥模板 `config.example.toml`，`.gitignore` 忽略 `config.toml`；运行态代码不再读取 `.env`。
2. `scripts/start.sh` 缺失 `config.toml` 时明确报错退出；提供 `config.toml`（或 `TRACEAGENT_CONFIG` / `CONFIG_FILE`）时可正常拉起全部服务并将端口、S3、数据库、模型与 `HF_HUB_DISABLE_IMPLICIT_TOKEN` 正确传递。
3. 单独启动 `agent`、`document_service`、`backend`、`storage` 时可直接从 `config.toml` 读取对应配置，且显式进程环境变量可覆盖文件值。
4. `shared`、`agent`、`backend`、`scripts`、`.github` 相关单元测试全部通过。

### Phase 2 (模型总结会话标题)
1. 现有旧 SQLite 数据库启动时自动补齐 `chat_sessions.title` 列，不丢失历史数据。
2. 新建会话发起首轮提问后，异步调用 `AgentService.GenerateTitle` 生成可读标题并持久化，同时不阻塞主问答 SSE 流；标题模型报错或超时时主问答仍正常完成并有安全兜底标题。
3. `GET /chat/sessions` 与 `GET /chat/sessions/{id}/resume` 返回可读 `title`，最近会话抽屉不再展示 UUID。
4. 新增 `agent` 标题生成单测、`backend` 异步触发/落库/兜底/旧库迁移单测与 `frontend` 会话列表展示单测全部通过。

### Phase 3 (前端重设计)
1. 全站品牌名更新为 `TraceAgent`；首页无左侧空栏与快捷提示卡，选文件后行内展示队列状态/错误红字/重试，全部就绪仍自动跳转详情页并保留未发草稿。
2. 详情页 Light 模式下左原文 `#FAFAFA`、分割线 `#E6E6E6`、右对话纯白 `#FFFFFF`、钢蓝 `#3978C8`；Dark 模式下外层与右对话切为 `#141414`/`#181818`/`#222222`，左侧打开的原始文档正文恒定保持 `#FAFAFA` 白纸黑字。
3. 点击引用后左侧以柔光块高亮目标段（无左边框弯钩），仅滚动左侧文档容器不拉扯外层页面，且绝不重置用户拖拽后的左右栏宽度。
4. `pnpm --dir frontend test --runInBand`（含 `frontend-copy.test.ts`）、`pnpm --dir frontend lint`、`pnpm --dir frontend build` 全部通过；另以真实本地全栈服务 + 真实浏览器实测 Light/Dark 切换、引用高亮与滚动、拖拽分栏以及模型总结标题落库展示。
5. `python3 scripts/check_docs.py` 全通过，且三个阶段对应 `DESIGN.md`、`DECISIONS.md`、`DEVLOG.md` 与 [document-qa-workbench.md](../../product-specs/document-qa-workbench.md) 同步更新。

## Decision Log

- 选定柔光块 (`rgba(57, 120, 200, 0.13)` + 左侧贴边 3px 钢蓝直竖条) 作为原文引用默认高亮，排除黄色荧光与行内划词。-> 已迁入 [frontend/src/components/DECISIONS.md](../../../frontend/src/components/DECISIONS.md)
- 选定原始文档正文在 Light 与 Dark 模式下恒定保持 `#FAFAFA` 白纸黑字，右侧 Agent Feed 采用 Antigravity / Codex 中性色阶 (Light `#FFFFFF`，Dark `#181818`)。-> 已迁入 [frontend/src/components/DECISIONS.md](../../../frontend/src/components/DECISIONS.md)
- 选定首页移除左侧空栏与快捷提示卡，工作台品牌名统一为 `TraceAgent`，非内容 UI 大幅图标化并继续维持英文运行态文案门禁。-> 已迁入 [frontend/src/components/DECISIONS.md](../../../frontend/src/components/DECISIONS.md)
- 选定会话标题由 `agent` 提供 `GenerateTitle` gRPC 由模型异步总结生成并由 `backend` 落库，避免在 `backend` 直接推理模型，旧会话与失败场景安全降级不显示 UUID。-> 已迁入 [agent_proto/DECISIONS.md](../../../agent_proto/DECISIONS.md) 与 [backend/services/DECISIONS.md](../../../backend/services/DECISIONS.md)
- 选定全仓配置文件由 `.env` 切换为基于 Python 3.11 `tomllib` 的单文件 `config.toml`，由 `shared` 提供统一加载器。-> 已迁入 [shared/traceagent_shared/DECISIONS.md](../../../shared/traceagent_shared/DECISIONS.md) 与 [scripts/docs/DECISIONS.md](../../../scripts/docs/DECISIONS.md)
