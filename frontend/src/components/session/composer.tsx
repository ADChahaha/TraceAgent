"use client";

import { useRef, useState } from "react";
import { Paperclip, Pause, SendHorizonal } from "lucide-react";
import { DOCUMENT_ACCEPT } from "@/lib/document-files";
import { Button } from "@/components/ui/button";

export function SessionComposer({ running, disabled, canCancel, cancelling, onSend, onCancel, onUpload, uploadDisabled, initialDraft = "" }: {
  initialDraft?: string;
  onUpload: (files: File[]) => void; uploadDisabled: boolean;
  running: boolean; disabled: boolean; canCancel: boolean; cancelling: boolean;
  onSend: (content: string) => void; onCancel: () => void;
}) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [draft, setDraft] = useState(initialDraft);
  function send() {
    if (running || disabled || !draft.trim()) return;
    onSend(draft.trim());
    setDraft("");
  }
  return <form className="replay-agent-composer" aria-label="QA composer" onSubmit={(event) => { event.preventDefault(); send(); }}>
    <div className="replay-agent-composer-balance-row">
      <textarea aria-label="QA question input" value={draft} onChange={(event) => setDraft(event.target.value)}
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
    <div className="mt-2">
      <Button type="button" variant="ghost" size="sm" disabled={uploadDisabled} onClick={() => fileInput.current?.click()}>
        <Paperclip size={16} />Add files
      </Button>
      <input ref={fileInput} type="file" className="sr-only" aria-label="Attach documents" accept={DOCUMENT_ACCEPT} multiple disabled={uploadDisabled}
        onChange={(event) => {
          const files = Array.from(event.target.files ?? []);
          event.target.value = "";
          if (files.length) onUpload(files);
        }} />
    </div>
  </form>;
}
