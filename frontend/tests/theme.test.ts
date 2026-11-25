import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const globalsCss = readFileSync(resolve(__dirname, "../src/app/globals.css"), "utf8");
const workspaceCss = readFileSync(resolve(__dirname, "../src/components/session/workspace.module.css"), "utf8");
const sourcesCss = readFileSync(resolve(__dirname, "../src/components/session/sources.module.css"), "utf8");
const conversationCss = readFileSync(resolve(__dirname, "../src/components/session/conversation.module.css"), "utf8");

function cssRule(css: string, selector: string) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return css.match(new RegExp(`(?:^|\\n)${escaped}\\s*\\{([^}]*)\\}`))?.[1] ?? "";
}

it("TraceAgent 主题使用统一的 Antigravity / Codex 中性色阶、柔光高亮与暗色白纸文档", () => {
  expect(globalsCss).toContain("--background: #ffffff;");
  expect(globalsCss).toContain("--foreground: #171717;");
  expect(globalsCss).toContain("--border: #e6e6e6;");
  expect(globalsCss).toContain("--codex-accent: #3978c8;");
  expect(globalsCss).toContain("--background: #181818;");
  expect(globalsCss).toContain("--card: #222222;");
  expect(globalsCss).toContain("--codex-accent: #4e8ee0;");

  expect(workspaceCss).toContain("--ws-left-bg: #fafafa;");
  expect(workspaceCss).toContain("--ws-chat-bg: #ffffff;");
  expect(workspaceCss).toContain("--ws-line: #e6e6e6;");
  expect(workspaceCss).toContain("--ws-accent: #3978c8;");
  expect(workspaceCss).toContain("--ws-topbar-bg: #141414;");
  expect(workspaceCss).toContain("--ws-chat-bg: #181818;");
  expect(workspaceCss).toContain("--ws-elevated-bg: #222222;");
  expect(workspaceCss).toContain("--ws-accent: #4e8ee0;");
  expect(workspaceCss).toContain("--ws-paper-bg: #fafafa;");
  expect(workspaceCss).toContain("--ws-paper-gutter: 8px;");

  expect(sourcesCss).toContain("--replay-foreground: #171717;");
  expect(sourcesCss).toContain("border-radius: 0 6px 6px 0;");
  expect(sourcesCss).toContain("background: rgba(57, 120, 200, 0.13);");
  expect(sourcesCss).toContain("border-left-color: #3978c8;");
});

it("默认详情页左右分栏给右侧 Agent 对话区更大宽度，拖动条显式占位", () => {
  expect(workspaceCss).toContain("var(--source-width, 36%)");
  expect(workspaceCss).toMatch(/\.root :global\(\.replay-panel-resize-handle\)\s*\{[^}]*display:\s*inline-flex;/);
});

it("Agent 正文和行内链接在窄宽度下完整折行，容器查询支持窄列模式", () => {
  const reasonTextRule = cssRule(globalsCss, ".replay-agent-reason-text");
  expect(reasonTextRule).toContain("overflow-wrap: anywhere;");
  expect(reasonTextRule).toContain("word-break: break-word;");

  const evidenceLinkRule = cssRule(globalsCss, ".replay-evidence-link");
  expect(evidenceLinkRule).toContain("display: inline;");
  expect(evidenceLinkRule).toContain("overflow-wrap: anywhere;");
  expect(evidenceLinkRule).toContain("word-break: break-word;");

  expect(globalsCss).toContain("container-type: inline-size;");
  expect(globalsCss).toMatch(/@container\s*\(max-width:\s*360px\)/);
});

it("工具过程折叠条采用极简 trace-mini 布局并支持窄列换行", () => {
  expect(conversationCss).toContain("list-style: none;");
  expect(conversationCss).toContain("transform: rotate(90deg);");
  expect(conversationCss).toContain("flex-wrap: wrap;");
  expect(conversationCss).toContain("border-left: 1px solid var(--ws-line);");
});
