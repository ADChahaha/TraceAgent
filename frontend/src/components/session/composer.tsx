"use client";

import { useRef, useState } from "react";
import { Pause, SendHorizonal } from "lucide-react";
import { QuestionSuggestions } from "./workspace-overview";
import { Button } from "@/components/ui/button";

export function SessionComposer({ running, disabled, canCancel, cancelling, onSend, onCancel, initialDraft = "" }: {
  initialDraft?: string;
  running: boolean; disabled: boolean; canCancel: boolean; cancelling: boolean;
  onSend: (content: string) => void; onCancel: () => void;
}) {
  const input = useRef<HTMLTextAreaElement>(null);
  const [draft, setDraft] = useState(initialDraft);
  function send() {
    if (running || disabled || !draft.trim()) return;
    onSend(draft.trim());
    setDraft("");
  }
  return <form className="replay-agent-composer" aria-label="QA composer" onSubmit={(event) => { event.preventDefault(); send(); }}>
    <div className="replay-agent-composer-balance-row">
      <textarea ref={input} aria-label="QA question input" value={draft} onChange={(event) => setDraft(event.target.value)}
        placeholder="Ask a follow-up question" className="replay-agent-composer-input"
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey && !event.altKey && !event.ctrlKey && !event.metaKey && !event.nativeEvent.isComposing) { event.preventDefault(); send(); }
        }} />
      <div className="replay-agent-composer-actions" style={{ justifyContent: "flex-end" }}>
        <Button type="button" size="icon" aria-label="Submit or pause answer" disabled={running ? !canCancel || cancelling : disabled}
          onClick={() => running ? onCancel() : send()}>
          <span className="replay-agent-composer-action-icon-shell" aria-hidden="true">
            <SendHorizonal className="replay-agent-composer-action-icon h-4 w-4" data-visible={running ? "false" : "true"} />
            <Pause className="replay-agent-composer-action-icon h-4 w-4" data-visible={running ? "true" : "false"} />
          </span>
        </Button>
      </div>
    </div>
    <QuestionSuggestions onSelect={(prompt) => { setDraft(prompt); input.current?.focus(); }} />
  </form>;
}
