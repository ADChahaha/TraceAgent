"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { BookOpen } from "lucide-react";
import { listSessions, type SessionSummary } from "@/lib/api";
import { subscribeSessions } from "@/lib/session-store";

export function WorkspaceList({ sessionId, onSelect }: { sessionId?: string; onSelect: () => void }) {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let disposed = false;
    let version = 0;
    async function refresh() {
      const request = ++version;
      try {
        const result = await listSessions();
        if (!disposed && request === version) { setSessions(result.sessions); setError(null); }
      } catch {
        if (!disposed && request === version) setError("Could not load workspaces. Reopen this menu to retry.");
      } finally { if (!disposed && request === version) setLoading(false); }
    }
    void refresh();
    window.addEventListener("focus", refresh);
    const unsubscribe = subscribeSessions(refresh);
    return () => { disposed = true; unsubscribe(); window.removeEventListener("focus", refresh); };
  }, []);
  return <nav aria-label="Recent sessions">
    {loading && <p role="status">Loading workspaces...</p>}
    {error && <p role="alert">{error}</p>}
    {!loading && !error && sessions.length === 0 && <p>No workspaces yet.</p>}
    {sessions.map((session) => <Link key={session.id} href={`/tasks/${encodeURIComponent(session.id)}`} onClick={onSelect} aria-current={session.id === sessionId ? "page" : undefined}>
      <BookOpen size={18} /><span>{session.id}<small>{session.active_turn_id ? "running" : session.status}</small></span>
    </Link>)}
  </nav>;
}
