"use client";

import { useEffect, useRef, useState } from "react";
import { FileText, Loader2, Plus, SendHorizonal, X } from "lucide-react";
import { createSession, openCompletion } from "@/lib/api";
import { consumeSessionStream } from "@/lib/session-stream";
import { rememberSession } from "@/lib/session-store";
import { DOCUMENT_ACCEPT } from "@/lib/document-files";
import { useFileUploads } from "@/lib/use-file-uploads";
import { UploadStatus } from "@/components/session/upload-status";
import Link from "next/link";
import { WorkspaceShell } from "@/components/session/workspace-shell";
import { Button } from "@/components/ui/button";
import { WorkspaceOverview, QuestionSuggestions } from "@/components/session/workspace-overview";
import styles from "@/components/session/workspace.module.css";
import { Textarea } from "@/components/ui/textarea";

export function UploadWorkbench({ onCreated, onFilesReady }: { onCreated?: (sessionId: string) => void; onFilesReady?: (sessionId: string, draft: string) => void }) {
  const [question, setQuestion] = useState("");
  const [sourceRequest, setSourceRequest] = useState(0);
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
      if (!signal.aborted) setError(cause instanceof Error ? cause.message : "Failed to start session");
    } finally {
      lock.current = false;
      if (!signal.aborted) setSubmitting(false);
    }
  }

  function choosePrompt(prompt: string) {
    setQuestion(prompt);
    document.getElementById("first-question")?.focus();
  }
  const sources = <section className={styles.sources}>
    <div className={styles.sourceHeading}><h2>Sources</h2><span>{files.length}</span></div>
    <ul className={styles.sourceList} aria-label="Sources list">
      {uploads.items.map((item) => <li key={item.file.name}>
        <FileRow item={item} submitting={submitting} busy={uploads.busy} onRetry={() => uploads.retry(item.file)} onRemove={() => void uploads.remove(item.file)} />
      </li>)}
    </ul>
    {!files.length && <div className={styles.sourceEmpty}><FileText size={30} strokeWidth={1.3} /><p>Your sources live here</p><small>Add a PDF or Word document to get started.</small></div>}
    <button type="button" className={styles.addSource} disabled={submitting} onClick={() => fileInput.current?.click()}><Plus size={19} />Add source</button>
  </section>;
  return <WorkspaceShell sessionId={createdId ?? undefined} review={sources} reviewRequest={sourceRequest}>
    <main className={styles.home} aria-label="Agent task workspace">
      <WorkspaceOverview count={files.length} onAdd={() => fileInput.current?.click()} onPrompt={choosePrompt} />
      <form className={styles.firstComposer} aria-label="Create task composer" onSubmit={(event) => { event.preventDefault(); void submit(); }}>
        <input ref={fileInput} type="file" multiple accept={DOCUMENT_ACCEPT} aria-label="Document file input" className="sr-only" disabled={submitting} onChange={(event) => {
          const selected = Array.from(event.target.files ?? []);
          uploads.add(selected);
          setSourceRequest((value) => value + 1);
          event.target.value = ""; setError(null);
        }} />
        <div className={styles.inputRow}>
          <Textarea id="first-question" aria-label="QA question input" value={question} onChange={(event) => setQuestion(event.target.value)}
            placeholder="Ask a question about your sources..." disabled={submitting}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.altKey && !event.ctrlKey && !event.metaKey && !event.nativeEvent.isComposing) {
                event.preventDefault(); void submit();
              }
            }} />
          <Button type="submit" size="icon" aria-label="Upload documents and ask" disabled={submitting || uploads.busy || (files.length > 0 && !uploads.ready)}>
            {submitting ? <Loader2 size={20} className="animate-spin" /> : <SendHorizonal size={20} />}
          </Button>
        </div>
        {(error || uploads.error) && <div className="home-task-composer-error" role="alert">{error ?? uploads.error}</div>}
        <QuestionSuggestions onSelect={choosePrompt} />
        <div className={styles.composerHint}>{submitting ? "Starting your answer..." : uploads.busy ? "Processing sources..." : files.length ? `${files.length} document${files.length > 1 ? "s" : ""}` : "Add sources to start a conversation"}</div>
        {createdId && !uploads.busy && <Link className="text-xs underline" href={`/tasks/${createdId}`}>Open workspace</Link>}
      </form>
    </main>
  </WorkspaceShell>;
}

function FileRow({ item, submitting, busy, onRetry, onRemove }: {
  item: import("@/lib/use-file-uploads").FileUpload; submitting: boolean; busy: boolean; onRetry: () => void; onRemove: () => void;
}) {
  const file = item.file;
  return <>
    <span className={styles.fileIcon}><FileText size={23} /></span>
    <span className={styles.fileName}>{file.name}<small>{file.name.split(".").at(-1)?.toUpperCase()} · {(file.size / 1024).toFixed(1)} KB</small>{item.error && <small role="alert" className="text-destructive">{item.error}</small>}</span>
    <UploadStatus item={item} disabled={submitting} onRetry={onRetry} />
    <button type="button" disabled={submitting || ["processing", "removing"].includes(item.status) || (busy && item.status === "ready")} aria-label={`Remove ${file.name}`} onClick={onRemove}><X size={16} /></button>
  </>;
}
