import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const globalsCss = readFileSync(resolve(__dirname, "../src/app/globals.css"), "utf8");

function cssRule(selector: string) {
  const escapedSelector = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return globalsCss.match(new RegExp(`(?:^|\\n)${escapedSelector}\\s*\\{([^}]*)\\}`))?.[1] ?? "";
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

it("Replay stage 在窄视口也使用左右栏列布局，不把 Review 原文栏堆到下方", () => {
  const baseStageBlock = globalsCss.match(/\.replay-stage\s*\{([^}]*)\}/)?.[1] ?? "";
  const baseFullscreenBlock = globalsCss.match(/\.replay-stage-fullscreen\s*\{([^}]*)\}/)?.[1] ?? "";
  expect(baseStageBlock).toContain("grid-template-columns: var(--replay-stage-columns, minmax(0, 1fr));");
  expect(baseStageBlock).toContain("column-gap: 8px;");
  expect(baseStageBlock).toContain("row-gap: 0;");
  expect(baseFullscreenBlock).toContain("column-gap: 0;");
});

it("Agent 阅读列按最小文字宽、可选文字宽、空白的顺序收缩", () => {
  expect(globalsCss).toContain("--replay-agent-readable-min-width: 520px;");
  expect(globalsCss).toContain("--replay-agent-readable-optional-width: 200px;");
  expect(globalsCss).toContain(
    "--replay-agent-readable-max-width: calc(var(--replay-agent-readable-min-width) + var(--replay-agent-readable-optional-width));",
  );
  expect(globalsCss).toMatch(
    /\.replay-agent-panel-slot\[data-agent-content-mode="centered"\]\s+\.replay-agent-content-frame,\s*\.replay-agent-panel-slot\[data-agent-content-mode="centered"\]\s+\.replay-agent-composer-frame\s*\{[\s\S]*grid-template-columns:\s*minmax\(0,\s*1fr\)\s*minmax\(min\(100%,\s*var\(--replay-agent-readable-min-width\)\),\s*var\(--replay-agent-readable-max-width\)\)\s*minmax\(0,\s*1fr\);/,
  );
  expect(globalsCss).not.toContain("--replay-agent-compact-gutter-width");
  expect(globalsCss).not.toContain("@container (max-width: 820px)");
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
