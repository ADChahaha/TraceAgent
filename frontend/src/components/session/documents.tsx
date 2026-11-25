"use client";

import { Download, FileText, Plus, Search, Trash2, X } from "lucide-react";
import styles from "./sources.module.css";
import { useEffect, useRef, useState } from "react";
import { listSessionDocuments, sessionFileUrl } from "@/lib/api";
import { formatUserError } from "@/lib/error-messages";
import type { FileUpload } from "@/lib/use-file-uploads";
import { UploadStatus } from "./upload-status";
import { DOCUMENT_ACCEPT } from "@/lib/document-files";
import { SourceReader, documentRoot, documentLabel } from "./source-reader";
import type { DocumentEntry, DocumentSelection, SessionResource } from "@/lib/session-types";

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
    }).catch((error) => { if (!cancelled) setListError(formatUserError(error, "document")); });
    return () => { cancelled = true; };
  }, [sessionId, revision, hasDocuments]);
  const roots = [...new Set(entries.map((entry) => documentRoot(entry.key)))];
  const root = selection?.key ? documentRoot(selection.key) : null;

  if (root && hasDocuments) return <section className={styles.sources} aria-label="Document reader">
    <header className={styles.readerHeader}>
      <select aria-label="Source document" value={root} onChange={(event) => onSelect(event.target.value)}>
        {roots.map((key) => <option key={key} value={key}>{documentLabel(key)}</option>)}
      </select>
      <button type="button" className={styles.iconBtn} aria-label="Close document" title="Back to sources" onClick={onClose}>
        <X size={15} />
      </button>
    </header>
    <div className={styles.sourceContent} aria-label="Source content">
      <div className={styles.sourcePaper}>
        <SourceReader
          sessionId={sessionId}
          root={root}
          revision={revision}
          selection={selection}
          onSelect={onSelect}
        />
      </div>
    </div>
  </section>;

  const totalCount = raw.length + pending.filter((item) => !raw.some((resource) => resource.location.split("/").at(-1) === item.file.name)).length;
  return <section className={styles.sources} aria-label="Session documents">
    <div className={styles.sourcesControls}>
      <div className={styles.sourceHeading}>
        <h2>Sources</h2>
        <span className={styles.sourceCount}>{totalCount}</span>
        <label className={styles.uploadLabel} title="Add files">
          <Plus size={15} strokeWidth={1.9} />
          <input ref={fileInput} type="file" className="sr-only" aria-label="Add session files" multiple accept={DOCUMENT_ACCEPT} disabled={disabled} onClick={() => onFilePickerChange?.(true)} onChange={(event) => {
            const files = Array.from(event.target.files ?? []);
            event.target.value = "";
            if (files.length) onUpload(files);
            onFilePickerChange?.(false);
          }} />
        </label>
      </div>
      <label className={styles.search}>
        <Search size={14} />
        <input type="search" aria-label="Search sources" placeholder="Search" value={search} onChange={(event) => setSearch(event.target.value)} />
      </label>
      {search && !filtered.length && !visibleUploads.length && <p className="px-4 py-2 text-xs text-muted-foreground">No matching sources</p>}
      <ul className={styles.sourceList} aria-label="Sources list">
        {visibleUploads.map((item) => <li key={`upload:${item.file.name}`}>
          <span className={styles.fileIcon}><FileText size={15} strokeWidth={1.75} /></span>
          <span className={styles.fileName}>
            {item.file.name}
            {item.error && <small role="alert">{item.error}</small>}
          </span>
          <UploadStatus item={item} disabled={disabled} onRetry={() => onRetry?.(item.file)} />
          {item.status === "failed" && <button type="button" className={styles.rowIconAction} aria-label={`Dismiss ${item.file.name}`} title={`Dismiss ${item.file.name}`} onClick={() => onDismiss?.(item.file)}>
            <X size={14} />
          </button>}
        </li>)}
        {filtered.map((resource) => {
          const name = resource.location.split("/").at(-1) ?? "Document";
          const stem = name.replace(/\.[^.]+$/, "").toLowerCase();
          const matchedRoot = roots.find((candidate) => documentLabel(candidate).toLowerCase() === stem);
          return <li key={resource.id}>
            <span className={styles.fileIcon}><FileText size={15} strokeWidth={1.75} /></span>
            {matchedRoot
              ? <button type="button" className={styles.fileName} onClick={() => onSelect(matchedRoot)} title={name}>{name}</button>
              : <span className={styles.fileName} title={name}>{name}</span>}
            <span className={styles.rowActions}>
              <a href={sessionFileUrl(sessionId, resource.id)} aria-label={`Download ${name}`} title={`Download ${name}`} className={styles.rowIconAction}>
                <Download size={14} strokeWidth={1.75} />
              </a>
              <button type="button" disabled={disabled || mutating} aria-label={`Remove ${name}`} title={`Remove ${name}`} onClick={() => onRemove(resource.id)} className={styles.rowIconAction}>
                <Trash2 size={14} strokeWidth={1.75} />
              </button>
            </span>
          </li>;
        })}
      </ul>
    </div>
    {listError && <p role="alert" className="p-3 text-xs text-destructive">{listError}</p>}
    {!hasDocuments && <p className="p-4 text-xs text-muted-foreground">Upload documents to start.</p>}
  </section>;
}
