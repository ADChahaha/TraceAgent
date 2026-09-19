"use client";

import { FileText, Plus, Search } from "lucide-react";
import styles from "./workspace.module.css";
import { useEffect, useState } from "react";
import { listSessionDocuments, readSessionBlock, readSessionDocument, sessionFileUrl } from "@/lib/api";
import { DOCUMENT_ACCEPT } from "@/lib/document-files";
import { MarkdownEvidence } from "@/components/markdown-evidence";
import type { DocumentContent, DocumentEntry, SessionResource } from "@/lib/session-types";

export interface DocumentSelection { key: string; block: boolean; version: number }
export function SessionDocuments({ sessionId, resources, disabled, selection, onSelect, onUpload, onRemove }: {
  sessionId: string; resources: SessionResource[]; disabled: boolean;
  selection: DocumentSelection | null; onSelect: (key: string) => void;
  onUpload: (files: File[]) => void; onRemove: (id: string) => void;
}) {
  const [search, setSearch] = useState("");
  const raw = resources.filter((resource) => resource.type === "raw");
  const filtered = raw.filter((resource) => resource.location.split("/").at(-1)?.toLowerCase().includes(search.toLowerCase()));
  const [entries, setEntries] = useState<DocumentEntry[]>([]);
  const [result, setResult] = useState<{ id: string; key: string; version: number; content?: DocumentContent; error?: string } | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const hasDocuments = resources.some((resource) => resource.type === "documents");
  useEffect(() => {
    let cancelled = false;
    if (!hasDocuments) return;
    listSessionDocuments(sessionId).then((value) => {
      if (!cancelled) { setEntries(value.documents); setListError(null); }
    }).catch((error) => { if (!cancelled) setListError(error instanceof Error ? error.message : "Failed to list documents"); });
    return () => { cancelled = true; };
  }, [sessionId, resources, hasDocuments]);
  const key = selection?.key ?? (hasDocuments ? entries[0]?.key : undefined);
  const block = selection?.block ?? false;
  const version = selection?.version ?? 0;
  useEffect(() => {
    let cancelled = false;
    if (!key || !hasDocuments) return;
    (block ? readSessionBlock : readSessionDocument)(sessionId, key).then((content) => {
      if (!cancelled) setResult({ id: sessionId, key, version, content });
    }).catch((error) => {
      if (!cancelled) setResult({ id: sessionId, key, version, error: error instanceof Error ? error.message : "Failed to read document" });
    });
    return () => { cancelled = true; };
  }, [sessionId, key, block, version, hasDocuments, resources]);
  const shown = result?.id === sessionId && result.key === key && result.version === version ? result : null;
  return <section className={styles.sources} aria-label="Session documents">
    <div className={styles.documentControls}>
      <div className={styles.sourceHeading}><h2>Sources</h2><span>{raw.length}</span>
        <label className={styles.uploadLabel}><Plus size={16} />Add files<input type="file" className="sr-only" aria-label="Add session files" multiple accept={DOCUMENT_ACCEPT} disabled={disabled} onChange={(event) => {
          const files = Array.from(event.target.files ?? []); event.target.value = ""; if (files.length) onUpload(files);
        }} /></label>
      </div>
      <label className={styles.search}><Search size={16} /><input type="search" aria-label="Search sources" placeholder="Search sources" value={search} onChange={(event) => setSearch(event.target.value)} /></label>
      {search && !filtered.length && <p className="text-sm text-muted-foreground">No matching sources</p>}
      <ul className={styles.sourceList} aria-label="Sources list">
        {filtered.map((resource) => {
          const name = resource.location.split("/").at(-1) ?? "Document";
          return <li key={resource.id} >
            <span className={styles.fileIcon}><FileText size={21} /></span>
            <a href={sessionFileUrl(sessionId, resource.id)} aria-label={`Download ${name}`} className={styles.fileName}>{name}<small>{name.split(".").at(-1)?.toUpperCase()} · Download</small></a>
            <button disabled={disabled} aria-label={`Remove ${name}`} onClick={() => onRemove(resource.id)} className="text-muted-foreground disabled:opacity-40">Remove</button>
          </li>;
        })}
      </ul>
      {hasDocuments && <select aria-label="Source document" className="w-full rounded border bg-background p-2 text-xs" value={key ?? ""} onChange={(event) => onSelect(event.target.value)}>
        {entries.map((entry) => <option key={entry.key} value={entry.key}>{entry.key.replace(/^documents\//, "")}</option>)}
      </select>}
    </div>
    <div className={styles.sourceContent} aria-label="Source content">
      {!hasDocuments ? <p className="text-sm text-muted-foreground">Upload documents to start.</p> : <>
        {listError && <p role="alert">{listError}</p>}
        {shown?.error && <p role="alert">{shown.error}</p>}
        {!shown && key && <p className="text-sm text-muted-foreground">Loading source...</p>}
        {shown?.content && <div className={block ? "rounded border border-blue-300 bg-blue-50/10 p-3" : ""}>
          <MarkdownEvidence markdown={shown.content.text} onOpenEvidence={(uri) => onSelect(uri)} />
        </div>}
      </>}
    </div>
  </section>;
}
