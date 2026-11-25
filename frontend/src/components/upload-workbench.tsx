"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowUp, FileText, Loader2, Paperclip, X } from "lucide-react";
import { createSession, openCompletion } from "@/lib/api";
import { formatUserError } from "@/lib/error-messages";
import { consumeSessionStream } from "@/lib/session-stream";
import { rememberSession } from "@/lib/session-store";
import { DOCUMENT_ACCEPT } from "@/lib/document-files";
import { useFileUploads, type FileUpload } from "@/lib/use-file-uploads";
import { UploadStatus } from "@/components/session/upload-status";
import { WorkspaceShell } from "@/components/session/workspace-shell";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import styles from "@/components/session/workspace.module.css";

export function UploadWorkbench({ onCreated, onFilesReady }: {
  onCreated?: (sessionId: string) => void;
  onFilesReady?: (sessionId: string, draft: string) => void;
}) {
  const [question, setQuestion] = useState("");
  const [createdId, setCreatedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const sessionId = useRef<string | null>(null);
  const lock = useRef(false);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => { controller.current?.abort(); }, []);

  const uploads = useFileUploads(async () => {
    if (!sessionId.current) {
      sessionId.current = (await createSession()).session_id;
      rememberSession(sessionId.current);
      setCreatedId(sessionId.current);
    }
    return sessionId.current;
  });
  const files = uploads.items.map((item) => item.file);
  const opened = useRef(false);
  useEffect(() => {
    if (createdId && uploads.ready && onFilesReady && !opened.current) {
      opened.current = true;
      onFilesReady(createdId, question);
    }
  }, [createdId, uploads.ready, onFilesReady, question]);

  async function submit() {
    if (lock.current || uploads.busy) return;
    const invalid = !files.length ? "Select at least one PDF or DOCX file"
      : !uploads.ready ? "Retry or remove failed files before asking"
      : !question.trim() ? "Enter a question" : null;
    if (invalid) { setError(invalid); return; }
    lock.current = true;
    setSubmitting(true);
    setError(null);
    controller.current = new AbortController();
    const signal = controller.current.signal;
    try {
      const id = sessionId.current!;
      if (signal.aborted) return;
      const response = await openCompletion(id, question.trim(), signal);
      let accepted = false;
      await consumeSessionStream(response, (frame) => {
        if (frame.event !== "session.snapshot") return;
        if (frame.data.session_id !== id) throw new Error("Unexpected session snapshot");
        accepted = true;
        rememberSession(id, frame.data);
        return true;
      }, signal);
      if (!accepted) throw new Error("Connection interrupted. Open the session to check its status before resending.");
      if (!signal.aborted) onCreated?.(id);
    } catch (cause) {
      if (!signal.aborted) setError(formatUserError(cause, "chat"));
    } finally {
      lock.current = false;
      if (!signal.aborted) setSubmitting(false);
    }
  }

  return <WorkspaceShell sessionId={createdId ?? undefined}>
    <main className={styles.home} aria-label="Agent task workspace">
      <div className={styles.homeCenter}>
        <h1 className={styles.homeTitle}>TraceAgent</h1>
        <form className={styles.firstComposer} aria-label="Create task composer" onSubmit={(event) => { event.preventDefault(); void submit(); }}>
          <input ref={fileInput} type="file" multiple accept={DOCUMENT_ACCEPT} aria-label="Document file input" className="sr-only" disabled={submitting} onChange={(event) => {
            const selected = Array.from(event.target.files ?? []);
            uploads.add(selected);
            event.target.value = "";
            setError(null);
          }} />
          {uploads.items.length > 0 && <ul className={styles.inlineFileList} aria-label="Sources list">
            {uploads.items.map((item) => <li key={item.file.name} className={styles.inlineFileRow}>
              <InlineFileRow item={item} submitting={submitting} busy={uploads.busy} onRetry={() => uploads.retry(item.file)} onRemove={() => void uploads.remove(item.file)} />
            </li>)}
          </ul>}
          <Textarea id="first-question" aria-label="QA question input" className={styles.homeTextarea} value={question} onChange={(event) => setQuestion(event.target.value)}
            placeholder="Ask a question about your documents..." disabled={submitting}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.altKey && !event.ctrlKey && !event.metaKey && !event.nativeEvent.isComposing) {
                event.preventDefault(); void submit();
              }
            }} />
          {(error || uploads.error) && <div className="home-task-composer-error" role="alert">{error ?? uploads.error}</div>}
          <div className={styles.composerBar}>
            <div className={styles.composerBarLeft}>
              <button type="button" className={styles.attachBtn} aria-label="Add sources" title="Add PDF or DOCX files" disabled={submitting} onClick={() => fileInput.current?.click()}>
                <Paperclip size={16} strokeWidth={1.8} />
              </button>
              <span className={styles.composerHint}>
                {submitting ? "Starting answer..." : uploads.busy ? "Processing..." : files.length ? `${files.length} document${files.length > 1 ? "s" : ""}` : "PDF, DOCX"}
              </span>
            </div>
            <Button type="submit" size="icon" className={styles.sendBtn} aria-label="Upload documents and ask" disabled={submitting || uploads.busy || (files.length > 0 && !uploads.ready)}>
              {submitting ? <Loader2 size={16} className="animate-spin" /> : <ArrowUp size={16} strokeWidth={2.2} />}
            </Button>
          </div>
          {createdId && !uploads.busy && <Link className={styles.workspaceLink} href={`/tasks/${createdId}`}>Open workspace</Link>}
        </form>
      </div>
    </main>
  </WorkspaceShell>;
}

function InlineFileRow({ item, submitting, busy, onRetry, onRemove }: {
  item: FileUpload; submitting: boolean; busy: boolean; onRetry: () => void; onRemove: () => void;
}) {
  const file = item.file;
  return <>
    <FileText size={15} strokeWidth={1.75} />
    <span className={styles.inlineFileName}>
      {file.name}
      {item.error && <small role="alert">{item.error}</small>}
    </span>
    <UploadStatus item={item} disabled={submitting} onRetry={onRetry} />
    <button type="button" className={styles.rowIconAction} disabled={submitting || ["processing", "removing"].includes(item.status) || (busy && item.status === "ready")} aria-label={`Remove ${file.name}`} title={`Remove ${file.name}`} onClick={onRemove}>
      <X size={14} />
    </button>
  </>;
}
