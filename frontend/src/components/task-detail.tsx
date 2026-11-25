"use client";

import { readWorkspaceDraft, saveWorkspaceDraft } from "@/lib/session-store";
import { useEffect, useMemo, useRef, useState } from "react";
import { removeSessionFile } from "@/lib/api";
import { documentKey } from "@/lib/document-files";
import { formatUserError } from "@/lib/error-messages";
import { useFileUploads } from "@/lib/use-file-uploads";
import { useSession } from "@/lib/use-session";
import { WorkspaceShell } from "@/components/session/workspace-shell";
import { Conversation } from "@/components/session/conversation";
import { SessionComposer } from "@/components/session/composer";
import type { DocumentSelection } from "@/lib/session-types";
import { SessionDocuments } from "@/components/session/documents";

export function TaskDetail({ taskId }: { taskId: string }) {
  return <SessionWorkspace key={taskId} sessionId={taskId} />;
}

function SessionWorkspace({ sessionId }: { sessionId: string }) {
  const session = useSession(sessionId);
  const [initialDraft] = useState(() => readWorkspaceDraft(sessionId));
  const [selection, setSelection] = useState<DocumentSelection | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [sourceRequest, setSourceRequest] = useState(0);
  const [fileBusy, setFileBusy] = useState(false);
  const fileLock = useRef(false);
  const filePickerOpen = useRef(false);
  const resources = useMemo(() => session.snapshot?.state.resources ?? [], [session.snapshot]);
  const unavailable = !session.snapshot || !["idle", "live"].includes(session.connection);

  const uploads = useFileUploads(async () => sessionId, () => { setSelection(null); session.refresh(); });

  useEffect(() => {
    // Let server snapshot take over completed files so removals from another tab do not leave stale rows.
    for (const item of uploads.items) {
      if (item.status === "ready" && resources.some((resource) => resource.type === "raw" && resource.location.split("/").at(-1) === item.file.name)) uploads.forget(item.file.name);
    }
  }, [uploads, resources]);

  const canRefresh = !fileBusy && !uploads.busy && !session.running && session.connection === "idle";
  const refreshSession = session.refresh;
  useEffect(() => {
    const refresh = () => { if (canRefresh && !filePickerOpen.current) refreshSession(); };
    window.addEventListener("focus", refresh);
    const timer = canRefresh ? window.setInterval(refresh, 5000) : undefined;
    return () => { window.removeEventListener("focus", refresh); window.clearInterval(timer); };
  }, [canRefresh, refreshSession]);

  function addFiles(files: File[]) {
    if (fileBusy || session.running || unavailable) return;
    setSelection(null);
    uploads.add(files);
    setSourceRequest((value) => value + 1);
  }

  function openEvidence(uri: string, block = true) {
    const key = documentKey(uri);
    if (!key) { setFileError("This source link does not refer to a document in this session."); return; }
    setSelection((current) => ({ key, block, version: (current?.version ?? 0) + 1 }));
  }

  async function removeFile(resourceId: string) {
    if (fileLock.current || uploads.busy || session.running || unavailable) return;
    fileLock.current = true;
    setFileBusy(true);
    setFileError(null);
    try {
      await removeSessionFile(sessionId, resourceId);
      const name = resources.find((resource) => resource.id === resourceId)?.location.split("/").at(-1);
      if (name) uploads.forget(name);
      setSelection(null);
      session.refresh();
    } catch (cause) {
      setFileError(formatUserError(cause, "remove"));
      session.refresh();
    } finally { fileLock.current = false; setFileBusy(false); }
  }

  const review = session.snapshot ? <SessionDocuments sessionId={sessionId} resources={resources}
    disabled={fileBusy || session.running || unavailable} mutating={uploads.busy} uploads={uploads.items} onRetry={uploads.retry} onDismiss={(file) => void uploads.remove(file)} selection={selection}
    onSelect={(key) => openEvidence(key, false)} onClose={() => setSelection(null)} onUpload={addFiles} onFilePickerChange={(open) => { filePickerOpen.current = open; }}
    onRemove={(id) => void removeFile(id)} /> : undefined;

  return <main className="task-detail-fullscreen-shell" aria-label="Task detail workspace">
    <WorkspaceShell
      sessionId={sessionId}
      sessionTitle={session.snapshot?.state.title}
      status={fileBusy || uploads.busy ? "Updating documents" : session.connection}
      review={review}
      reviewRequest={(selection?.version ?? 0) + sourceRequest}
    >
      <section className="replay-agent-panel-slot" aria-label="Agent workspace" data-agent-content-mode="centered">
        <div className="replay-agent-panel">
          {(session.error || fileError || uploads.error) && <div role="alert" className="border-b p-3 text-sm text-destructive">
            {fileError ?? uploads.error ?? session.error}
            {session.connection === "reconnecting" ? <span> Reconnecting...</span> : session.error && <button onClick={() => session.refresh()} className="ml-2 underline">Reconnect</button>}
          </div>}
          {!session.snapshot && <p className="p-4 text-sm text-muted-foreground">Loading session...</p>}
          <Conversation
            turns={session.snapshot?.state.turns ?? []}
            running={session.running}
            pending={session.pending}
            activeEvidenceKey={selection?.block ? selection.key : null}
            onEvidence={(uri) => openEvidence(uri)}
          />
          <SessionComposer initialDraft={initialDraft} running={session.running} canCancel={Boolean(session.snapshot?.state.active_turn_id)} cancelling={session.cancelling}
            disabled={unavailable || fileBusy || uploads.busy || uploads.items.some((item) => item.status === "failed") || !resources.some((resource) => resource.type === "documents")}
            onSend={(content) => { saveWorkspaceDraft(sessionId, ""); session.send(content); }} onCancel={() => void session.cancel()} />
        </div>
      </section>
    </WorkspaceShell>
  </main>;
}
