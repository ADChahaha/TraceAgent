"use client";

import { BookOpen } from "lucide-react";
import styles from "@/components/session/workspace.module.css";
import { useRef, useState } from "react";
import { removeSessionFile, uploadSessionFiles } from "@/lib/api";
import { documentKey, validateFiles } from "@/lib/document-files";
import { useSession } from "@/lib/use-session";
import { WorkspaceShell } from "@/components/session/workspace-shell";
import { Conversation } from "@/components/session/conversation";
import { SessionComposer } from "@/components/session/composer";
import { SessionDocuments, type DocumentSelection } from "@/components/session/documents";

export function TaskDetail({ taskId }: { taskId: string }) {
  return <SessionWorkspace key={taskId} sessionId={taskId} />;
}

function SessionWorkspace({ sessionId }: { sessionId: string }) {
  const session = useSession(sessionId);
  const [selection, setSelection] = useState<DocumentSelection | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [fileBusy, setFileBusy] = useState(false);
  const fileLock = useRef(false);
  const resources = session.snapshot?.state.resources ?? [];
  const unavailable = !session.snapshot || !["idle", "live"].includes(session.connection);

  function openEvidence(uri: string, block = true) {
    const key = documentKey(uri);
    if (!key) { setFileError("This source link does not refer to a document in this session."); return; }
    setSelection((current) => ({ key, block, version: (current?.version ?? 0) + 1 }));
  }

  async function changeFiles(files?: File[], resourceId?: string) {
    if (fileLock.current || session.running || unavailable) return;
    if (files) {
      const invalid = validateFiles(files);
      if (invalid) { setFileError(invalid); return; }
    }
    fileLock.current = true;
    setFileBusy(true);
    setFileError(null);
    try {
      if (files) await uploadSessionFiles(sessionId, files);
      else if (resourceId) await removeSessionFile(sessionId, resourceId);
      setSelection(null);
      session.refresh();
    } catch (cause) {
      setFileError(cause instanceof Error ? cause.message : "File operation failed");
      session.refresh();
    } finally { fileLock.current = false; setFileBusy(false); }
  }

  const review = session.snapshot ? <SessionDocuments sessionId={sessionId} resources={resources}
    disabled={fileBusy || session.running || unavailable} selection={selection}
    onSelect={(key) => openEvidence(key, false)} onUpload={(files) => void changeFiles(files)}
    onRemove={(id) => void changeFiles(undefined, id)} /> : undefined;
  return <main className="task-detail-fullscreen-shell" aria-label="Task detail workspace">
    <WorkspaceShell sessionId={sessionId} status={fileBusy ? "Updating documents" : session.connection} review={review} reviewRequest={selection?.version}>
      <section className="replay-agent-panel-slot" aria-label="Agent workspace" data-agent-content-mode="centered">
        <div className="replay-agent-panel">
          <header className={styles.sessionHeading}><BookOpen size={25} /><div><h1>Document conversation</h1><p>{resources.filter((resource) => resource.type === "raw").length} sources · Answers grounded in your documents</p></div></header>
          {(session.error || fileError) && <div role="alert" className="border-b p-3 text-sm text-destructive">
            {fileError ?? session.error}
            {session.connection === "reconnecting" ? <span> Reconnecting...</span> : session.error && <button onClick={() => session.refresh()} className="ml-2 underline">Reconnect</button>}
          </div>}
          {!session.snapshot && <p className="p-4 text-sm text-muted-foreground">Loading session...</p>}
          <Conversation turns={session.snapshot?.state.turns ?? []} running={session.running} pending={session.pending} onEvidence={(uri) => openEvidence(uri)} />
          <SessionComposer running={session.running} canCancel={Boolean(session.snapshot?.state.active_turn_id)} cancelling={session.cancelling}
            disabled={unavailable || fileBusy || !resources.some((resource) => resource.type === "documents")}
            onSend={session.send} onCancel={() => void session.cancel()} />
        </div>
      </section>
    </WorkspaceShell>
  </main>;
}
