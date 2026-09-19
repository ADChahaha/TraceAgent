import type { SessionSnapshot } from "@/lib/session-types";

export interface RecentSession { id: string; status: string; updatedAt: string }
const KEY = "agent-gate.recent-sessions";
const CHANGED = "agent-gate-sessions-changed";
const EMPTY: RecentSession[] = [];
let cachedRaw: string | null = null;
let cached = EMPTY;

export function recentSessions(): RecentSession[] {
  if (typeof window === "undefined") return EMPTY;
  try {
    const raw = localStorage.getItem(KEY) ?? "[]";
    if (raw !== cachedRaw) {
      const parsed: unknown = JSON.parse(raw);
      cached = Array.isArray(parsed) ? parsed.filter((item) => item && typeof item.id === "string" && typeof item.status === "string").slice(0, 20) : EMPTY;
      cachedRaw = raw;
    }
    return cached;
  } catch { return EMPTY; }
}

export const serverSessions = () => EMPTY;
export function subscribeSessions(listener: () => void) {
  window.addEventListener(CHANGED, listener);
  window.addEventListener("storage", listener);
  return () => {
    window.removeEventListener(CHANGED, listener);
    window.removeEventListener("storage", listener);
  };
}

export function rememberSession(id: string, snapshot?: SessionSnapshot) {
  const status = snapshot?.state.active_turn_id ? "running" : snapshot?.state.status ?? "ready";
  const next = [{ id, status, updatedAt: new Date().toISOString() }, ...recentSessions().filter((item) => item.id !== id)].slice(0, 20);
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
    window.dispatchEvent(new Event(CHANGED));
  } catch { /* 缓存不可写时仍允许会话操作。 */ }
}
