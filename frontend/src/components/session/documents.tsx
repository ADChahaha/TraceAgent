"use client";

import { FileText, Plus, Search, X } from "lucide-react";
import styles from "./workspace.module.css";
import { useEffect, useRef, useState } from "react";
import { listSessionDocuments, sessionFileUrl } from "@/lib/api";
import type { FileUpload } from "@/lib/use-file-uploads";
import { UploadStatus } from "./upload-status";
import { DOCUMENT_ACCEPT } from "@/lib/document-files";
import { SourceReader, documentRoot, documentLabel } from "./source-reader";
import type { DocumentEntry, SessionResource } from "@/lib/session-types";

export interface DocumentSelection { key: string; block: boolean; version: number }
export function SessionDocuments({ sessionId, resources, disabled, selection, onSelect, onUpload, onRemove, uploads = [], mutating = false, onRetry, onDismiss, onClose, onFilePickerChange }: {
  uploads?: FileUpload[]; mutating?: boolean; onRetry?: (file: File) => void; onDismiss?: (file: File) => void;
  onClose: () => void; onFilePickerChange?: (open: boolean) => void;
  sessionId: string; resources: SessionResource[]; disabled: boolean;
  selection: DocumentSelection | null; onSelect: (key: string) => void;
  onUpload: (files: File[]) => void; onRemove: (id: string) => void;
}) {
  const fileInput = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const input = fileInput.current;
    const cancel = () => onFilePickerChange?.(false);
    input?.addEventListener("cancel", cancel);
    return () => { input?.removeEventListener("cancel", cancel); };
  }, [onFilePickerChange, selection]);
  const [search, setSearch] = useState("");
  const raw = resources.filter((resource) => resource.type === "raw");
  const pending = uploads.filter((item) => item.status !== "ready" || !raw.some((resource) => resource.location.split("/").at(-1) === item.file.name));
  const visibleUploads = pending.filter((item) => item.file.name.toLowerCase().includes(search.toLowerCase()));
  const filtered = raw.filter((resource) => resource.location.split("/").at(-1)?.toLowerCase().includes(search.toLowerCase()));
  const [entries, setEntries] = useState<DocumentEntry[]>([]);
  const [listError, setListError] = useState<string | null>(null);
  const hasDocuments = resources.some((resource) => resource.type === "documents");
  const revision = resources.filter((resource) => resource.type === "documents").map((resource) => `${resource.id}:${resource.location}`).join("|");
  useEffect(() => {
    let cancelled = false;
    if (!hasDocuments) return;
    listSessionDocuments(sessionId).then((value) => {
      if (!cancelled) { setEntries(value.documents); setListError(null); }
    }).catch((error) => { if (!cancelled) setListError(error instanceof Error ? error.message : "Failed to list documents"); });
    return () => { cancelled = true; };
  }, [sessionId, revision, hasDocuments]);
  const roots = [...new Set(entries.map((entry) => documentRoot(entry.key)))];
  const root = selection?.key ? documentRoot(selection.key) : null;
  if (root && hasDocuments) return <section className={styles.sources} aria-label="Document reader">
    <header className={styles.readerHeader}>
      <label><span>Source document</span><select aria-label="Source document" value={root} onChange={(event) => onSelect(event.target.value)}>
        {roots.map((key) => <option key={key} value={key}>{documentLabel(key)}</option>)}
      </select></label>
      <button type="button" aria-label="Close document" title="Back to sources" onClick={onClose}><X size={18} /></button>
    </header>
    <div className={styles.sourceContent} aria-label="Source content">
      <SourceReader sessionId={sessionId} root={root} revision={revision} selection={selection} onSelect={onSelect} />
    </div>
  </section>;
  return <section className={styles.sources} aria-label="Session documents">
    <div className={styles.sourcesControls}>
      <div className={styles.sourceHeading}><h2>Sources</h2><span>{raw.length + pending.filter((item) => !raw.some((resource) => resource.location.split("/").at(-1) === item.file.name)).length}</span>
        <label className={styles.uploadLabel}><Plus size={16} />Add files<input ref={fileInput} type="file" className="sr-only" aria-label="Add session files" multiple accept={DOCUMENT_ACCEPT} disabled={disabled} onClick={() => onFilePickerChange?.(true)} onChange={(event) => {
          const files = Array.from(event.target.files ?? []); event.target.value = ""; if (files.length) onUpload(files);
          onFilePickerChange?.(false);
        }} /></label>
      </div>
      <label className={styles.search}><Search size={16} /><input type="search" aria-label="Search sources" placeholder="Search sources" value={search} onChange={(event) => setSearch(event.target.value)} /></label>
      {search && !filtered.length && !visibleUploads.length && <p className="text-sm text-muted-foreground">No matching sources</p>}
      <ul className={styles.sourceList} aria-label="Sources list">
        {visibleUploads.map((item) => <li key={`upload:${item.file.name}`}>
          <span className={styles.fileIcon}><FileText size={21} /></span>
          <span className={styles.fileName}>{item.file.name}{item.error && <small role="alert" className="text-destructive">{item.error}</small>}</span>
          <UploadStatus item={item} disabled={disabled} onRetry={() => onRetry?.(item.file)} />
          {item.status === "failed" && <button aria-label={`Dismiss ${item.file.name}`} onClick={() => onDismiss?.(item.file)}>Remove</button>}
        </li>)}
        {filtered.map((resource) => {
          const name = resource.location.split("/").at(-1) ?? "Document";
          return <li key={resource.id} >
            <span className={styles.fileIcon}><FileText size={21} /></span>
            <a href={sessionFileUrl(sessionId, resource.id)} aria-label={`Download ${name}`} className={styles.fileName}>{name}<small>{name.split(".").at(-1)?.toUpperCase()} · Download</small></a>
            <button disabled={disabled || mutating} aria-label={`Remove ${name}`} onClick={() => onRemove(resource.id)} className="text-muted-foreground disabled:opacity-40">Remove</button>
          </li>;
        })}
      </ul>
    </div>
    {listError && <p role="alert" className="p-4 text-sm">{listError}</p>}
    {!hasDocuments && <p className="p-4 text-sm text-muted-foreground">Upload documents to start.</p>}
  </section>;
}
