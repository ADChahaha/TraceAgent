import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const globalsCss = readFileSync(resolve(__dirname, "../src/app/globals.css"), "utf8");

function cssRule(selector: string) {
  const escapedSelector = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return globalsCss.match(new RegExp(`${escapedSelector}\\s*\\{([^}]*)\\}`))?.[1] ?? "";
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
  expect(globalsCss).toMatch(/\.replay-agent-tool-group-toggle\s*\{[^}]*grid-template-columns:\s*auto minmax\(0,\s*1fr\);[^}]*gap:\s*8px;/);
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

it("Agent 阅读列先压缩弹性留白，再压缩正文宽度", () => {
  expect(globalsCss).toContain("--replay-agent-readable-max-width: 720px;");
  expect(globalsCss).toMatch(
    /\.replay-agent-panel-slot\[data-agent-content-mode="centered"\]\s+\.replay-agent-content-frame,\s*\.replay-agent-panel-slot\[data-agent-content-mode="centered"\]\s+\.replay-agent-composer-frame\s*\{[\s\S]*grid-template-columns:\s*minmax\(0,\s*1fr\)\s*minmax\(0,\s*var\(--replay-agent-readable-max-width\)\)\s*minmax\(0,\s*1fr\);/,
  );
  expect(globalsCss).not.toContain("--replay-agent-compact-gutter-width");
  expect(globalsCss).not.toContain("@container (max-width: 820px)");
});
