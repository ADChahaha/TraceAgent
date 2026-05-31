import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const globalsCss = readFileSync(resolve(__dirname, "../src/app/globals.css"), "utf8");

function cssRule(selector: string) {
  const escapedSelector = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return globalsCss.match(new RegExp(`(?:^|\\n)${escapedSelector}\\s*\\{([^}]*)\\}`))?.[1] ?? "";
}

function cssRuleContainingSelector(selector: string) {
  return (
    Array.from(globalsCss.matchAll(/(?:^|\n)([^{}]+)\{([^}]*)\}/g)).find((match) =>
      match[1].split(",").some((item) => item.trim() === selector),
    )?.[2] ?? ""
  );
}

it("Codex 主题使用统一的 light/dark token", () => {
  expect(globalsCss).toContain("--foreground: #1a1c1f;");
  expect(globalsCss).toContain("--secondary: #f4f4f5;");
  expect(globalsCss).toContain("--muted-foreground: #6f6f76;");
  expect(globalsCss).toContain("--codex-accent: #339cff;");
  expect(globalsCss).toContain("--background: #181818;");
  expect(globalsCss).toContain("--card: #202020;");
  expect(globalsCss).toContain("--secondary: #262626;");
  expect(globalsCss).toContain("--accent: #2a2a2a;");
  expect(globalsCss).toContain("--border: #303030;");
});

it("工作台面板和代码块都复用主题表面变量", () => {
  expect(globalsCss).toMatch(/\.replay-agent-panel\s*\{[\s\S]*background:\s*var\(--replay-panel\);/);
  expect(globalsCss).toMatch(/\.replay-plan-tool-panel\s*\{[\s\S]*background:\s*var\(--replay-panel\);/);
  expect(globalsCss).toMatch(/\.replay-tool-timeline-panel\s*\{[\s\S]*background:\s*var\(--replay-panel\);/);
  expect(globalsCss).toMatch(/\.replay-tool-tree,\s*\.replay-tool-markdown-result pre\s*\{[\s\S]*background:\s*var\(--replay-tool-surface\);/);
  expect(globalsCss).toMatch(/\.replay-dialogue-main\s*\{[\s\S]*background:\s*var\(--replay-dialogue-bg\);/);
});

it("Agent turn 使用更开的上下间距，工具行内部保持紧凑", () => {
  expect(globalsCss).toMatch(/\.replay-agent-turn\s*\{[^}]*gap:\s*14px;/);
  expect(globalsCss).toMatch(/\.replay-agent-tool-line\s*\{[^}]*gap:\s*8px;/);
  expect(globalsCss).toMatch(/\.replay-agent-tool-group\s*\{[^}]*gap:\s*8px;/);
  expect(globalsCss).toMatch(/\.replay-agent-tool-group-toggle\s*\{[^}]*grid-template-columns:\s*auto minmax\(0,\s*1fr\) auto;[^}]*gap:\s*8px;/);
  expect(cssRule(".replay-agent-tool-group-lines")).not.toContain("padding-left:");
  expect(cssRule(".replay-agent-tool-group-chevron")).toContain("transition: transform 140ms ease;");
  expect(globalsCss).toMatch(/\.replay-agent-tool-group\.is-expanded\s+\.replay-agent-tool-group-chevron\s*\{[^}]*transform:\s*rotate\(90deg\);/);
  expect(globalsCss).toMatch(/\.replay-agent-tool-icon\s*\{[^}]*height:\s*14px;[^}]*width:\s*14px;/);
  expect(globalsCss).toMatch(/\.home-task-file-remove\s*\{[^}]*width:\s*18px;[^}]*height:\s*18px;/);
});

it("Agent 文本和工具摘要在窄宽度下换行，不用隐藏省略裁剪", () => {
  const reasonTextRule = cssRule(".replay-agent-reason-text");
  expect(reasonTextRule).toContain("overflow-wrap: anywhere;");
  expect(reasonTextRule).toContain("word-break: break-word;");

  const evidenceLinkRule = cssRule(".replay-evidence-link");
  expect(evidenceLinkRule).toContain("display: inline;");
  expect(evidenceLinkRule).toContain("padding: 0 1px;");
  expect(evidenceLinkRule).toContain("overflow-wrap: anywhere;");
  expect(evidenceLinkRule).toContain("word-break: break-word;");

  for (const selector of [".replay-agent-tool-summary", ".replay-agent-tool-group-summary"]) {
    const rule = cssRule(selector);
    expect(rule).toContain("white-space: normal;");
    expect(rule).toContain("overflow-wrap: anywhere;");
    expect(rule).toContain("word-break: break-word;");
    expect(rule).not.toContain("overflow: hidden;");
    expect(rule).not.toContain("text-overflow: ellipsis;");
  }
});

it("右侧 review 不再渲染文档 header", () => {
  expect(cssRule(".replay-source-header")).toBe("");
  expect(cssRule(".replay-source-header-copy")).toBe("");
  expect(cssRule(".replay-source-title")).toBe("");
  expect(cssRule(".replay-source-meta")).toBe("");

  const sourceFrameRule = cssRule(".replay-source-frame");
  expect(sourceFrameRule).toContain("background: #fff;");
});

it("Replay stage 在窄视口也使用左右栏列布局，不把 Review 原文栏堆到下方", () => {
  const baseStageBlock = globalsCss.match(/\.replay-stage\s*\{([^}]*)\}/)?.[1] ?? "";
  const baseFullscreenBlock = globalsCss.match(/\.replay-stage-fullscreen\s*\{([^}]*)\}/)?.[1] ?? "";
  expect(baseStageBlock).toContain("grid-template-columns: var(--replay-stage-columns, minmax(0, 1fr));");
  expect(baseStageBlock).toContain("column-gap: 8px;");
  expect(baseStageBlock).toContain("row-gap: 0;");
  expect(baseFullscreenBlock).toContain("column-gap: 0;");
});

it("Agent 对话流和 composer 使用同一套左右 inset 铺满中间 panel", () => {
  expect(globalsCss).toContain("--replay-agent-horizontal-inset: 18px;");
  expect(globalsCss).toContain("--replay-agent-readable-min-width: 520px;");
  expect(globalsCss).toContain("--replay-agent-readable-optional-width: 200px;");
  expect(globalsCss).toContain(
    "--replay-agent-readable-max-width: calc(var(--replay-agent-readable-min-width) + var(--replay-agent-readable-optional-width));",
  );
  expect(globalsCss).toContain("--replay-agent-panel-compact-min-width: 280px;");
  expect(globalsCss).toContain("--replay-review-panel-compact-min-width: 280px;");

  const fullWidthColumnRule = /grid-template-columns:\s*0\s+minmax\(0,\s*1fr\)\s+0;/;
  for (const selector of [
    '.replay-agent-panel-slot[data-agent-content-mode="centered"] .replay-agent-content-frame',
    '.replay-agent-panel-slot[data-agent-content-mode="centered"] .replay-agent-composer-frame',
    '.replay-agent-panel-slot[data-agent-content-mode="full"] .replay-agent-content-frame',
    '.replay-agent-panel-slot[data-agent-content-mode="full"] .replay-agent-composer-frame',
  ]) {
    expect(cssRuleContainingSelector(selector)).toMatch(fullWidthColumnRule);
  }

  const readableColumnRule = cssRule(".replay-agent-readable-column");
  expect(readableColumnRule).toContain("width: 100%;");
  expect(readableColumnRule).not.toContain("max-width: var(--replay-agent-readable-max-width);");
  expect(readableColumnRule).not.toContain("justify-self: center;");

  const composerReadableColumnRule = cssRule(".replay-agent-composer-readable-column");
  expect(composerReadableColumnRule).toContain("width: 100%;");
  expect(composerReadableColumnRule).not.toContain("max-width: var(--replay-agent-readable-max-width);");
  expect(composerReadableColumnRule).not.toContain("justify-self: center;");

  expect(globalsCss).not.toContain("--replay-agent-left-outer-width");
  expect(globalsCss).not.toContain("--replay-agent-right-outer-width");
  expect(globalsCss).not.toContain("--replay-agent-centered-column-width");
  expect(globalsCss).not.toContain("--replay-agent-left-balance-width");
  expect(globalsCss).not.toContain("--replay-agent-right-balance-width");
  expect(globalsCss).not.toContain("--replay-agent-compact-gutter-width");
  expect(globalsCss).not.toContain("@container (max-width: 820px)");

  const streamRule = cssRule(".replay-agent-stream");
  expect(streamRule).toContain("padding: 16px var(--replay-agent-horizontal-inset) 18px;");

  const composerRule = cssRule(".replay-agent-composer");
  expect(composerRule).toContain("padding: 12px var(--replay-agent-horizontal-inset);");
});

it("Agent 被右侧 review 挤窄时使用紧凑阅读模式", () => {
  const agentSlotRule =
    Array.from(globalsCss.matchAll(/(?:^|\n)\.replay-agent-panel-slot\s*\{([^}]*)\}/g))
      .map((match) => match[1])
      .find((rule) => rule.includes("container-type")) ?? "";
  expect(agentSlotRule).toContain("container-type: inline-size;");

  expect(globalsCss).toMatch(
    /@container\s*\(max-width:\s*360px\)\s*\{[\s\S]*?\.replay-agent-stream\s*\{[^}]*padding:\s*14px 12px 16px;/
  );
  expect(globalsCss).toMatch(
    /@container\s*\(max-width:\s*360px\)\s*\{[\s\S]*?\.replay-agent-composer\s*\{[^}]*padding:\s*10px 12px;/
  );
  expect(globalsCss).toMatch(
    /@container\s*\(max-width:\s*360px\)\s*\{[\s\S]*?\.qa-message-bubble\s*\{[^}]*max-width:\s*100%;/
  );
  expect(globalsCss).toMatch(
    /@container\s*\(max-width:\s*360px\)\s*\{[\s\S]*?\.replay-agent-reason-text\s*\{[^}]*font-size:\s*12px;[^}]*text-align:\s*left;/
  );
});

it("Contents 面板保留可读宽度、纵向滚动和多行文本", () => {
  const outlineListRule = cssRule(".replay-outline-panel-list");
  expect(outlineListRule).toContain("min-height: 0;");
  expect(outlineListRule).toContain("overflow-y: auto;");
  expect(outlineListRule).toContain("overflow-x: hidden;");

  const outlineLabelRule = cssRule(".replay-outline-item-label");
  expect(outlineLabelRule).toContain("white-space: normal;");
  expect(outlineLabelRule).toContain("overflow-wrap: anywhere;");
  expect(outlineLabelRule).not.toContain("overflow: hidden;");
  expect(outlineLabelRule).not.toContain("text-overflow: ellipsis;");

  const outlineValueRule = cssRule(".replay-outline-item-value");
  expect(outlineValueRule).toContain("max-width: 100%;");
  expect(outlineValueRule).toContain("white-space: normal;");
  expect(outlineValueRule).not.toContain("overflow: hidden;");
  expect(outlineValueRule).not.toContain("text-overflow: ellipsis;");
});

it("首页首屏只让 Tasks 列表成为滚动容器，整页工作台不滚动", () => {
  const homeWorkbenchRule = cssRule(".home-task-workbench");
  expect(homeWorkbenchRule).toContain("position: fixed !important;");
  expect(homeWorkbenchRule).toContain("inset: 0;");
  expect(homeWorkbenchRule).toContain("height: 100svh;");
  expect(homeWorkbenchRule).toContain("overflow: hidden;");

  const homeStageRule = cssRule(".home-task-stage");
  expect(homeStageRule).toContain("height: calc(100svh - var(--replay-topbar-h));");
  expect(homeStageRule).toContain("overflow: hidden;");

  expect(globalsCss).toMatch(
    /\.home-task-workbench\[data-left-panel-open="true"\]\s+\.home-task-stage\s*\{[^}]*grid-template-columns:\s*var\(--replay-left-panel-width\)\s+10px\s+minmax\(0,\s*1fr\);/
  );

  const sidebarRule =
    Array.from(globalsCss.matchAll(/(?:^|\n)\.replay-task-sidebar\s*\{([^}]*)\}/g))
      .map((match) => match[1])
      .find((rule) => rule.includes("border-right")) ?? "";
  expect(sidebarRule).toContain("height: 100%;");
  expect(sidebarRule).toContain("min-height: 0;");
  expect(sidebarRule).toContain("overflow: hidden;");

  const sidebarInnerRule = cssRule(".replay-task-sidebar-inner");
  expect(sidebarInnerRule).toContain("height: 100%;");
  expect(sidebarInnerRule).toContain("min-height: 0;");

  const taskListRule = cssRule(".replay-task-list");
  expect(taskListRule).toContain("flex: 1 1 auto;");
  expect(taskListRule).toContain("min-height: 0;");
  expect(taskListRule).toContain("overflow-y: auto;");
  expect(taskListRule).toContain("overflow-x: hidden;");
});

it("首页打开左侧栏时窄视口仍保留侧栏和拖拽手柄", () => {
  expect(globalsCss).toMatch(
    /\.home-task-workbench\[data-left-panel-open="true"\]\s+\.home-task-stage\s*\{[^}]*grid-template-columns:\s*var\(--replay-left-panel-width\)\s+10px\s+minmax\(0,\s*1fr\);/
  );
  expect(globalsCss).toMatch(
    /\.home-task-workbench\s+\.replay-panel-resize-handle,\s*\.replay-task-workbench\s+\.replay-panel-resize-handle\s*\{[^}]*display:\s*inline-flex;/
  );
  expect(globalsCss).not.toMatch(
    /@media\s*\(max-width:\s*900px\)\s*\{[\s\S]*?\.home-task-workbench\[data-left-panel-open="true"\]\s+\.home-task-stage,\s*\.home-task-workbench\[data-left-panel-open="false"\]\s+\.home-task-stage\s*\{[\s\S]*?grid-template-columns:\s*minmax\(0,\s*1fr\);/
  );
  expect(globalsCss).not.toMatch(
    /@media\s*\(max-width:\s*900px\)\s*\{[\s\S]*?\.home-task-workbench\s+\.replay-task-sidebar\s*\{[\s\S]*?display:\s*none;/
  );
  expect(globalsCss).toMatch(
    /@media\s*\(max-width:\s*900px\)\s*\{[\s\S]*?\.home-task-workbench\[data-left-panel-open="false"\]\s+\.replay-task-sidebar,\s*\.home-task-workbench\[data-left-panel-open="false"\]\s+\.replay-panel-resize-handle\s*\{[\s\S]*?display:\s*none;/
  );
});
