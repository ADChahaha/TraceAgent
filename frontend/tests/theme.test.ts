import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const globalsCss = readFileSync(resolve(__dirname, "../src/app/globals.css"), "utf8");

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
