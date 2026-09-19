"use client";

import { createElement, useEffect, useRef, useState } from "react";
import { readFullDocument } from "@/lib/api";
import type { FullDocument } from "@/lib/session-types";
import { MarkdownEvidence } from "@/components/markdown-evidence";
import type { DocumentSelection } from "./documents";
import styles from "./workspace.module.css";

export function documentRoot(key: string) { return key.split("/").slice(0, 2).join("/"); }
export function documentLabel(key: string) {
  return (key.split("/").at(-1) ?? key).replace(/^\d+-/, "").replace(/\.md$/, "").replace(/-Processed (?:DOCX|PDF)$/, "");
}

export function SourceReader({ sessionId, root, revision, selection, onSelect }: {
  sessionId: string; root: string; revision: string; selection: DocumentSelection | null; onSelect: (key: string) => void;
}) {
  const [result, setResult] = useState<{ id: string; root: string; revision: string; document?: FullDocument; error?: string } | null>(null);
  const nodes = useRef(new Map<string, HTMLDivElement>());
  useEffect(() => {
    let cancelled = false;
    readFullDocument(sessionId, root).then((document) => {
      if (!cancelled) setResult({ id: sessionId, root, revision, document });
    }).catch((cause) => {
      if (!cancelled) setResult({ id: sessionId, root, revision, error: cause instanceof Error ? cause.message : "Failed to read document" });
    });
    return () => { cancelled = true; };
  }, [sessionId, root, revision]);
  const shown = result?.id === sessionId && result.root === root && result.revision === revision ? result : null;
  const selectedKey = selection?.block ? selection.key : null;
  useEffect(() => {
    if (selectedKey && shown?.document) nodes.current.get(selectedKey)?.scrollIntoView?.({ block: "center", behavior: window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  }, [selectedKey, selection?.version, shown?.document]);
  if (!shown) return <p className="text-sm text-muted-foreground">Loading document...</p>;
  if (shown.error) return <p role="alert">{shown.error}</p>;
  const blocks = shown.document?.blocks ?? [];
  return <article aria-label="Full document" className={styles.fullDocument}>
    <h2 className={styles.documentTitle}>{documentLabel(root)}</h2>
    {selectedKey && !blocks.some((block) => block.key === selectedKey) && <p role="alert">This cited passage is no longer available in the document.</p>}
    {blocks.map((block, blockIndex) => {
      const previousSections = blocks[blockIndex - 1]?.key.split("/").slice(2, -1) ?? [];
      const sections = block.key.split("/").slice(2, -1);
      let shared = 0;
      while (shared < sections.length && sections[shared] === previousSections[shared]) shared++;
      const headings = sections.slice(shared).map((section, index) => createElement(`h${Math.min(shared + index + 2, 6)}`, { key: sections.slice(0, shared + index + 1).join("/") }, documentLabel(section)));
      return <div key={block.key}>
        {headings}
        <div ref={(node) => { if (node) nodes.current.set(block.key, node); else nodes.current.delete(block.key); }}
          data-source-key={block.key} data-evidence-selected={selectedKey === block.key ? "true" : "false"}
          className={styles.sourceBlock}>
          <MarkdownEvidence markdown={block.text} onOpenEvidence={onSelect} />
        </div>
      </div>;
    })}
  </article>;
}
