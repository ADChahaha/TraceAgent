import type { SessionSnapshot } from "@/lib/session-types";

const CHANGED = "agent-gate-sessions-changed";
const drafts = new Map<string, string>();

export function subscribeSessions(listener: () => void) {
  window.addEventListener(CHANGED, listener);
  return () => window.removeEventListener(CHANGED, listener);
}

export function rememberSession(id: string, snapshot?: SessionSnapshot) {
  window.dispatchEvent(new CustomEvent(CHANGED, { detail: { id, status: snapshot?.state.status } }));
}

// 仅交接首页导航前的未发送草稿，会话事实和目录均从后端读取。
export function saveWorkspaceDraft(id: string, draft: string) { drafts.set(id, draft); }
export function readWorkspaceDraft(id: string) { return drafts.get(id) ?? ""; }
