"use client";

import { useLayoutEffect, useRef } from "react";
import { ChevronRight, Search } from "lucide-react";
import { MarkdownEvidence } from "@/components/markdown-evidence";
import { formatUserError } from "@/lib/error-messages";
import type { SessionItem, SessionTurn } from "@/lib/session-types";
import { formatToolAction } from "@/lib/tool-labels";
import styles from "./conversation.module.css";

export function Conversation({ turns, running, pending, activeEvidenceKey, onEvidence }: {
  turns: SessionTurn[];
  running: boolean;
  pending: string | null;
  activeEvidenceKey?: string | null;
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
    <div className="replay-agent-centered-content space-y-5">
      {turns.map((turn) => <div key={turn.id} className="space-y-3" aria-label={`Turn ${turn.id}`}>
        {groupItems(turn.items).map((group) => group[0].kind === "tool"
          ? <ToolTrace key={group[0].id} items={group} />
          : <Message key={group[0].id} item={group[0]} activeEvidenceKey={activeEvidenceKey} onEvidence={onEvidence} />)}
        {turn.status === "cancelled" && <div className="replay-agent-empty">Cancelled</div>}
        {turn.status === "failed" && turn.error && <div role="alert" className="text-sm text-destructive">{formatUserError(turn.error, "chat")}</div>}
      </div>)}
      {pending && <div className="qa-message-turn is-user"><div className="qa-message-bubble whitespace-pre-wrap">{pending}</div></div>}
      {running && <div className="qa-thinking-turn" aria-label="Assistant is thinking"><div className="qa-thinking-bubble">Thinking<span className="qa-thinking-bounce" aria-hidden="true"><span /><span /><span /></span></div></div>}
      {!running && turns.length === 0 && <p className="replay-agent-empty">Ask a question to start multi-turn QA.</p>}
    </div>
  </div>;
}

function ToolTrace({ items }: { items: SessionItem[] }) {
  const anyRunning = items.some((item) => item.status === "running");
  const summaryLabel = `${items.length} lookup ${items.length === 1 ? "step" : "steps"}`;
  return <details className={styles.toolTrace} data-running={anyRunning ? "true" : "false"}>
    <summary className={styles.toolTraceSummary} aria-label={summaryLabel} title={summaryLabel}>
      <Search size={13} strokeWidth={1.8} className={styles.toolTraceIcon} aria-hidden="true" />
      <span className={styles.toolTraceCount}>{items.length}</span>
      <ChevronRight size={12} strokeWidth={2} className={styles.toolTraceChevron} aria-hidden="true" />
    </summary>
    <div className={styles.toolTraceBody}>
      <div className={styles.toolTraceFlow} role="list" aria-label="Lookup steps">
        {items.map((item) => {
          const label = formatToolAction(item.name, item.status);
          return <span key={item.id} role="listitem" className={styles.toolTraceStep} data-status={item.status}>{label}</span>;
        })}
      </div>
    </div>
  </details>;
}

function Message({ item, activeEvidenceKey, onEvidence }: {
  item: SessionItem;
  activeEvidenceKey?: string | null;
  onEvidence: (uri: string, label: string) => void;
}) {
  if (item.kind === "retry") return <div className="text-xs text-muted-foreground">Retrying model request (attempt {String(item.detail?.attempt ?? "")})</div>;
  if (!item.text?.trim()) return null;
  const citation = item.kind === "assistant" && item.status === "completed" && !item.tool_calls?.length;
  return <div className={`replay-agent-turn qa-message-turn is-${item.kind}`}>
    <div className="qa-message-bubble">
      {item.kind === "user" ? <div className="whitespace-pre-wrap">{item.text}</div>
        : <MarkdownEvidence markdown={item.text} className="replay-agent-reason-text" evidencePlacement={citation ? "citation" : "inline"} activeEvidenceKey={activeEvidenceKey} onOpenEvidence={onEvidence} />}
      {["failed", "interrupted"].includes(item.status) && <small className="text-muted-foreground">{item.status === "failed" ? "Attempt failed" : "Interrupted"}</small>}
    </div>
  </div>;
}

function groupItems(items: SessionItem[]) {
  const groups: SessionItem[][] = [];
  for (const item of items) {
    // 跳过只有 tool_calls 而无可见正文的消息，避免把连续多批工具调用切碎成多行。
    if (item.kind !== "tool" && item.kind !== "retry" && !item.text?.trim()) continue;
    const last = groups.at(-1);
    if (item.kind === "tool" && last?.[0].kind === "tool") last.push(item);
    else groups.push([item]);
  }
  return groups;
}
