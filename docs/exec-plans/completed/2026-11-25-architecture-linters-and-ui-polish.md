# 执行计划: 300 行文件门禁、依赖倒置架构 Linter 与前端布局/工具过程优化

状态: 已完成 (2026-11-25)

## 目标与范围

将本次需求拆分为三个可独立验收的阶段，不破坏 [ARCHITECTURE.md](../../../ARCHITECTURE.md) 顶层单向分层与核心不变量:

### Phase 1: 300 行文件上限机械门禁与存量瘦身

- 新增独立架构/代码约束脚本 `scripts/check_architecture.py`（核心逻辑模块化拆分为 `scripts/arch_lint/`），内置单文件行数门禁: 限制手写代码文件（`.py`、`.ts`、`.tsx`、`.js`、`.jsx`、`.css`）不得超过 300 行，自动忽略 `.git`、`.venv`、`node_modules`、`.next`、`build`、`dist`、`memory`、`.agents`、`experiments`、`storage/data` 与自动生成的 protobuf 绑定（`*_pb2.py`、`*_pb2_grpc.py`、`*_pb2.pyi`）。
- 报错信息采用 OpenAI Harness Engineering 风格: 给出具体文件、当前行数与上限，并附可执行拆分建议，便于人与 Agent 依据输出直接修正。
- 清理 [tech-debt-tracker.md](../tech-debt-tracker.md) 已登记的前端未接入死代码（`replay-review.tsx` 2518 行、`types.ts` 321 行、`outline-panel.tsx`、`task-store.ts`、`json.ts` 及 `globals.css` 中的旧 replay 死样式与无效样式断言），并对现存超过 300 行的生产文件与测试文件做清晰职责拆分:
  - `frontend/src/app/globals.css` (2911 行 -> 清理未使用的旧 replay 样式)
  - `frontend/src/components/session/workspace.module.css` (559 行 -> 按主题拆分为 `workspace.module.css`、`home.module.css`、`sources.module.css`、`conversation.module.css`)
  - `document_service/document_processor/pdf/html.py` (551 行 -> 拆出 `html_tables.py`、`html_blocks.py`)
  - `backend/services/session_manager.py` (538 行 -> 拆出 `session_resource_mixin.py`、`session_files.py`、`session_title_worker.py`)
  - `shared/traceagent_shared/config.py` (460 行 -> 拆出 `config_values.py`、`config_exports.py`)
  - `backend/crud/crud.py` (381 行 -> 拆出 `sessions.py`、`resources.py`、`turns.py`)
  - `document_service/document_resources/documents.py` (325 行 -> 拆出 `html_tree.py`)
  - 拆分 6 个超 300 行的测试文件（`test_session_manager.py`、`test_loop.py`、`test_resource_application.py`、`test_mineru_html.py`、`test_manager.py`、`task-detail.test.tsx`）。

### Phase 2: 参考 OpenAI Harness Engineering 的分层与依赖倒置（DIP）架构 Linter 与改造

- 在 `scripts/check_architecture.py` 与 `scripts/arch_lint/` 中基于 Python `ast` 与 TypeScript/TSX import 解析实现静态依赖门禁，报错附违规规则说明、推荐抽象落点与 [ARCHITECTURE.md](../../../ARCHITECTURE.md) 指针:
  1. **顶层包单向分层门禁**:
     - `agent_proto` 不依赖任何仓库业务包；`shared` 不依赖 `storage`/`document_service`/`agent`/`backend`/`frontend`；`storage` 仅可依赖 `shared`。
     - `document_service` 与 `agent` 仅可向下依赖 `agent_proto` 与 `shared`，平级严禁互导，禁止依赖 `backend`/`storage`/`frontend`。
     - `backend` 仅经 `agent_proto` 契约与 `shared` 协作，禁止直接 import `document_service`/`agent`/`storage` 内部代码。
     - `frontend` 禁止直接引用跨服务端口或后端以下服务实现。
  2. **包内固定分层与依赖倒置（DIP）门禁**（对齐 `Types -> Config -> Repo -> Service/Core -> Runtime -> Routes/UI -> Composition Root`）:
     - `backend`: `models` -> `core` -> `crud` -> `services/protocols` -> `services` -> `routes` -> `main`。消除现存违规:
       - `backend/routes/chat.py` 不再跳过 `services` 直接 import `backend.crud`，会话列表查询收口到 `backend/services/session_catalog.py`。
       - 新增 `backend/services/protocols.py` 定义 `DatabaseProtocol`、`CompletionStream`、`AgentGateway`、`DocumentGateway` 等抽象 `Protocol`，核心编排层（`session_manager`、`turn_runtime`）仅依赖抽象契约，禁止在核心编排模块直接 import 具体传输实现（`agent_client`、`document_client`）或具体对象存储实现（`S3ObjectStore`），具体装配统一收口于 `backend/main.py`。
     - `agent`: `schemas` -> `core/contracts` -> `core/{messages,executor,graph,loop}`（纯核心编排仅依赖 `schemas` 与 `contracts`，禁止直接 import `core/model.py`、`core/tools/*`、`openai`、`traceagent_shared`）-> `core/{model,tools}`（具体适配器）-> `application` -> `routes` -> `main`。
     - `document_service`: `document_processor/schemas` 与 `document_resources/schemas` -> `document_resources/protocols` -> `document_processor` / `document_resources/{documents,index,resources,reader}`（核心模块依赖 `ObjectStore` 与抽象协议，不直接实例化具体 `S3ObjectStore`）-> `application` -> `routes` -> `main`。
     - `frontend`: `src/lib/session-types.ts`（零内部依赖）-> `src/lib/*`（禁止反向 import `components/` 或 `app/`）-> `src/components/ui/*`（仅允许依赖 `@/lib/utils`）-> `src/components/*`（禁止反向 import `app/`，禁止模块间循环依赖）-> `src/app/*`。消除现存 `documents.tsx <-> source-reader.tsx` 循环依赖（将 `DocumentSelection` 迁入 `src/lib/session-types.ts`）。
- 为新 linter 编写覆盖正反例的单元测试（`scripts/tests/test_check_architecture.py`），并将 `check_docs.py` 与 `check_architecture.py` 接入 `.github/workflows/ci.yml` 的 `repo-gates` job。

### Phase 3: 前端默认分栏比例、顶栏新建位置与 Tool 过程折叠展示重设计

1. **详情页默认分栏让对话区大于文件栏**:
   - 调整 `workspace.module.css` 与 `sidebar-resize.tsx` 的默认左栏比例为左 36% / 右 64%，使默认打开详情页时右侧 Agent 对话区明显宽于左侧文件栏。
   - 保持自由拖拽与键盘调节能力，且点击引用或切回 Sources 列表绝不重置用户拖拽后的宽度。
2. **顶栏 `+`（新对话）移至左侧**:
   - 在 `workspace-shell.tsx` 中将 `<Link href="/" aria-label="New workspace">`（`+` 图标按钮）从顶栏右侧 `controls` 移至顶栏左侧 `brand` 组，紧邻汉堡菜单（`Recent workspaces`），顺序为 `[历史抽屉] [新对话 +] [TraceAgent / 会话标题]`；顶栏右侧仅保留状态、窄屏切换与明暗主题按钮。
3. **Tool 过程折叠展示重设计（消除堆叠 + 隐藏原始工具名）**:
   - 修复 `conversation.tsx` 中空文本 `assistant` 消息（仅含 `tool_calls` 无可见文本）把连续工具调用拆成多行 `1 tool activity` 堆叠的问题。
   - 还原 v5 HTML 原型（`trace-mini`）风格，收敛为低噪紧凑单入口折叠条（放大镜图标 + 步骤数 + 展开箭头）。
   - 展开后按步骤展示所用工具与状态，经 `frontend/src/lib/tool-labels.ts` 映射为友好英文动作名（`ls` -> `Browse files`、`read` -> `Read passage`、`grep` -> `Keyword search`、`search_embedding` -> `Semantic search`，未知工具兜底 `Document lookup`），不再显示原始函数名；继续保持稳定 React key、失败工具中性配色不标红，并通过 `frontend-copy.test.ts` 全英文文案门禁。

## 非目标

- 不改动 gRPC 协议定义、SSE 事件格式与数据库表结构。
- 不修改 Agent 工具集本身与检索算法，仅做前端展示映射与架构层依赖边界收口。
- 不在生产代码中引入第三方前端 UI 框架或新的 Python 运行时依赖。

## 验收标准

1. **300 行门禁**: 运行 `python3 scripts/check_architecture.py` 返回退出码 0；约定范围内的全部手写文件均不超过 300 行；构造超过 300 行的临时样本时 linter 能准确失败并输出文件路径、行数与拆分建议。
2. **分层与依赖倒置门禁**: `check_architecture.py` 验证全仓跨包分层、包内分层、DIP 抽象边界与前端无循环依赖全部通过；构造跨层反向 import、核心层直连具体实现、路由直连 CRUD 或前端循环依赖等反例时均被准确拦截并给出修复指引；`scripts/tests/test_check_architecture.py` 与 `.github/workflows/ci.yml` 接入通过。
3. **全仓回归无损**: `backend`、`agent`、`document_service`、`shared`、`scripts`、`.github` 单元测试全部通过；`pnpm --dir frontend test --runInBand`、`pnpm --dir frontend lint`、`pnpm --dir frontend build` 全部通过。
4. **前端界面与真实渲染验收**:
   - 打开会话详情页时右侧 Agent 对话区明显宽于左侧文件栏，拖拽后点击引用和切换文件列表不重置宽度。
   - 顶栏 `+`（New workspace）位于左侧菜单按钮旁，点击正常回到首页发起新对话。
   - 一轮多次工具调用不再堆叠为多行 `1 tool activity`，折叠入口紧凑美观，展开后展示可读英文动作名且不暴露 `ls`/`grep`/`read`/`search_embedding` 原始名称。
   - 在真实浏览器中启动本地服务实测渲染效果（Light/Dark 双主题、分栏比例、顶栏按钮、工具折叠展开与引用高亮）。
5. **文档同步**: 同步更新受影响的 `DESIGN.md`、`DECISIONS.md`、`DEVLOG.md`、[document-qa-workbench.md](../../product-specs/document-qa-workbench.md)、[tech-debt-tracker.md](../tech-debt-tracker.md) 与 [docs/design-docs/index.md](../../design-docs/index.md)，`python3 scripts/check_docs.py` 通过。

## Decision Log

- 选定 300 行文件上限门禁覆盖全仓手写源码、CSS 与测试文件（仅豁免自动生成的 `*_pb2.py`/`*_pb2_grpc.py`/`*_pb2.pyi` 与第三方/构建目录），同步清理前端死代码并拆分现存超标文件实现 0 豁免；排除仅限生产代码或豁免 CSS/测试文件。-> 已迁入 [scripts/docs/DECISIONS.md](../../../scripts/docs/DECISIONS.md) 与 [core-beliefs.md](../../design-docs/core-beliefs.md)
- 选定 Tool 过程折叠入口还原 v5 HTML 原型的 `trace-mini` 风格（放大镜图标 + 步骤数 + 箭头），合并被空文本 assistant 消息打断的连续工具调用，展开后使用可读英文动作名映射而不展示 `ls`/`grep`/`read`/`search_embedding` 原始工具名；排除问号图标与把所有过程叙述全部隐藏。-> 已迁入 [frontend/src/components/DECISIONS.md](../../../frontend/src/components/DECISIONS.md)
- 选定详情页默认打开时左文件栏 36% / 右 Agent 对话区 64%，保持自由拖拽且点击引用或切回 Sources 不重置宽度；排除 50%/50% 对半或更极端的 32%/68%。-> 已迁入 [frontend/src/components/DECISIONS.md](../../../frontend/src/components/DECISIONS.md)
- 选定顶栏 `+`（New workspace）移至顶栏左侧紧邻最近会话菜单按钮，右侧仅保留状态、窄屏切换与主题切换按钮。-> 已迁入 [frontend/src/components/DECISIONS.md](../../../frontend/src/components/DECISIONS.md)
- 选定参考 OpenAI Harness Engineering 在 `scripts/check_architecture.py` 中落地跨包单向分层 + 包内固定分层与依赖倒置（DIP）静态检查，报错附可执行修复指引并接入 CI。-> 已迁入 [scripts/docs/DECISIONS.md](../../../scripts/docs/DECISIONS.md)、[backend/routes/DECISIONS.md](../../../backend/routes/DECISIONS.md)、[backend/services/DECISIONS.md](../../../backend/services/DECISIONS.md)、[document_service/document_resources/docs/DECISIONS.md](../../../document_service/document_resources/docs/DECISIONS.md) 与 [.github/docs/DECISIONS.md](../../../.github/docs/DECISIONS.md)
