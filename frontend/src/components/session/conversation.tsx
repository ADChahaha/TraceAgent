"use client";

import { useLayoutEffect, useRef } from "react";
import { MarkdownEvidence } from "@/components/markdown-evidence";
import type { SessionItem, SessionTurn } from "@/lib/session-types";

export function Conversation({ turns, running, pending, onEvidence }: {
  turns: SessionTurn[]; running: boolean; pending: string | null;
  onEvidence: (uri: string, label: string) => void;
}) {
  const scroll = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  useLayoutEffect(() => {
    if (scroll.current && follow.current) scroll.current.scrollTop = scroll.current.scrollHeight;
  }, [turns, pending, running]);
  return <div ref={scroll} className="replay-agent-stream" aria-label="QA conversation and reading process" onScroll={(event) => {
    const target = event.currentTarget;
    follow.current = target.scrollHeight - target.scrollTop - target.clientHeight <= 80;
  }}>
    <div className="replay-agent-centered-content space-y-4">
      {turns.map((turn) => <div key={turn.id} className="space-y-4" aria-label={`Turn ${turn.id}`}>
        {groupItems(turn.items).map((group) => group[0].kind === "tool"
          ? <details key={group[0].id} className="text-xs text-muted-foreground"><summary className="cursor-pointer">{group.length} tool {group.length === 1 ? "activity" : "activities"}</summary>
            {group.map((item) => <div key={item.id} className="py-1" aria-label={`tool ${item.name}`}>{item.name}: {item.status}</div>)}
          </details>
          : <Message key={group[0].id} item={group[0]} onEvidence={onEvidence} />)}
        {turn.status === "cancelled" && <div className="replay-agent-empty">Cancelled</div>}
        {turn.status === "failed" && turn.error && <div role="alert" className="text-sm text-destructive">{turn.error}</div>}
      </div>)}
      {pending && <div className="qa-message-turn is-user"><div className="qa-message-bubble whitespace-pre-wrap">{pending}</div></div>}
      {running && <div className="qa-thinking-turn" aria-label="Assistant is thinking"><div className="qa-thinking-bubble">Thinking<span className="qa-thinking-bounce" aria-hidden="true"><span /><span /><span /></span></div></div>}
      {!running && turns.length === 0 && <p className="replay-agent-empty">Ask a question to start multi-turn QA.</p>}
    </div>
  </div>;
}

function Message({ item, onEvidence }: { item: SessionItem; onEvidence: (uri: string, label: string) => void }) {
  if (item.kind === "retry") return <div className="text-xs text-muted-foreground">Retrying model request (attempt {String(item.detail?.attempt ?? "")})</div>;
  if (!item.text) return null;
  const citation = item.kind === "assistant" && item.status === "completed" && !item.tool_calls?.length;
  return <div className={`replay-agent-turn qa-message-turn is-${item.kind}`}>
    <div className="qa-message-bubble">
      {item.kind === "user" ? <div className="whitespace-pre-wrap">{item.text}</div>
        : <MarkdownEvidence markdown={item.text} className="replay-agent-reason-text" evidencePlacement={citation ? "citation" : "inline"} onOpenEvidence={onEvidence} />}
      {["failed", "interrupted"].includes(item.status) && <small className="text-muted-foreground">{item.status === "failed" ? "Attempt failed" : "Interrupted"}</small>}
    </div>
  </div>;
}

function groupItems(items: SessionItem[]) {
  const groups: SessionItem[][] = [];
  for (const item of items) {
    const last = groups.at(-1);
    if (item.kind === "tool" && last?.[0].kind === "tool") last.push(item);
    else groups.push([item]);
  }
  return groups;
}
