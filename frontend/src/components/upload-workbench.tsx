"use client";

import { useEffect, useRef, useState } from "react";
import { FileText, Loader2, Plus, SendHorizonal, X } from "lucide-react";
import { createSession, openCompletion, uploadSessionFiles } from "@/lib/api";
import { consumeSessionStream } from "@/lib/session-stream";
import { rememberSession } from "@/lib/session-store";
import { DOCUMENT_ACCEPT, mergeFiles, validateFiles } from "@/lib/document-files";
import { WorkspaceShell } from "@/components/session/workspace-shell";
import { Button } from "@/components/ui/button";
import { WorkspaceOverview, QuestionSuggestions } from "@/components/session/workspace-overview";
import styles from "@/components/session/workspace.module.css";
import { Textarea } from "@/components/ui/textarea";

export function UploadWorkbench({ onCreated }: { onCreated?: (sessionId: string) => void }) {
  const [question, setQuestion] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const sessionId = useRef<string | null>(null);
  const lock = useRef(false);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => { controller.current?.abort(); }, []);

  async function submit() {
    if (lock.current) return;
    const invalid = validateFiles(files) ?? (!question.trim() ? "Enter a question" : null);
    if (invalid) { setError(invalid); return; }
    lock.current = true;
    setSubmitting(true);
    setError(null);
    controller.current = new AbortController();
    const signal = controller.current.signal;
    try {
      const id = sessionId.current ?? (await createSession()).session_id;
      sessionId.current = id;
      rememberSession(id);
      await uploadSessionFiles(id, files);
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
      {files.map((file) => <li key={`${file.name}-${file.lastModified}-${file.size}`}>
        <span className={styles.fileIcon}><FileText size={23} /></span>
        <span className={styles.fileName}>{file.name}<small>{file.name.split(".").at(-1)?.toUpperCase()} · {(file.size / 1024).toFixed(1)} KB</small></span>
        <button type="button" disabled={submitting} aria-label={`Remove ${file.name}`} onClick={() => setFiles((current) => current.filter((entry) => entry !== file))}><X size={16} /></button>
      </li>)}
    </ul>
    {!files.length && <div className={styles.sourceEmpty}><FileText size={30} strokeWidth={1.3} /><p>Your sources live here</p><small>Add a PDF or Word document to get started.</small></div>}
    <button type="button" className={styles.addSource} disabled={submitting} onClick={() => fileInput.current?.click()}><Plus size={19} />Add source</button>
  </section>;
  return <WorkspaceShell review={sources}>
    <main className={styles.home} aria-label="Agent task workspace">
      <WorkspaceOverview count={files.length} onAdd={() => fileInput.current?.click()} onPrompt={choosePrompt} />
      <form className={styles.firstComposer} aria-label="Create task composer" onSubmit={(event) => { event.preventDefault(); void submit(); }}>
        <input ref={fileInput} type="file" multiple accept={DOCUMENT_ACCEPT} aria-label="Document file input" className="sr-only" disabled={submitting} onChange={(event) => {
          const selected = Array.from(event.target.files ?? []);
          setFiles((current) => mergeFiles(current, selected));
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
          <Button type="submit" size="icon" aria-label="Upload documents and ask" disabled={submitting}>
            {submitting ? <Loader2 size={20} className="animate-spin" /> : <SendHorizonal size={20} />}
          </Button>
        </div>
        {error && <div className="home-task-composer-error" role="alert">{error}</div>}
        <QuestionSuggestions onSelect={choosePrompt} />
        <div className={styles.composerHint}>{submitting ? "Preparing your workspace..." : files.length ? `${files.length} document${files.length > 1 ? "s" : ""}` : "Add sources to start a conversation"}</div>
      </form>
    </main>
  </WorkspaceShell>;
}
