"use client";

import { useEffect, useRef, useState } from "react";
import { removeSessionFile, uploadSessionFiles } from "@/lib/api";
import { validateFiles } from "@/lib/document-files";
import type { SessionResource } from "@/lib/session-types";

export interface FileUpload {
  file: File;
  status: "queued" | "processing" | "ready" | "failed" | "removing";
  error?: string;
}

export function useFileUploads(getSessionId: () => Promise<string>, onChanged?: (resources: SessionResource[]) => void) {
  const [items, setItems] = useState<FileUpload[]>([]);
  const [error, setError] = useState<string | null>(null);
  const current = useRef<FileUpload[]>([]);
  const resources = useRef<SessionResource[]>([]);
  const working = useRef(false);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

  function publish(next: FileUpload[]) {
    current.current = next;
    if (mounted.current) setItems(next);
  }
  function update(file: File, patch: Partial<FileUpload>) {
    publish(current.current.map((item) => item.file === file ? { ...item, ...patch } : item));
  }
  async function process() {
    if (working.current) return;
    working.current = true;
    try {
      while (mounted.current) {
        const next = current.current.find((item) => item.status === "queued");
        if (!next) break;
        update(next.file, { status: "processing", error: undefined });
        try {
          const id = await getSessionId();
          if (!mounted.current) break;
          const result = await uploadSessionFiles(id, [next.file]);
          resources.current = result.resources;
          update(next.file, { status: "ready" });
          if (mounted.current) onChanged?.(result.resources);
        } catch (cause) {
          update(next.file, { status: "failed", error: cause instanceof Error ? cause.message : "Processing failed" });
        }
      }
    } finally { working.current = false; }
  }
  function add(files: File[]) {
    const incoming = files.filter((file, index) => !current.current.some((item) => item.file.name === file.name)
      && files.findIndex((entry) => entry.name === file.name) === index);
    if (!incoming.length) return;
    const invalid = validateFiles([...current.current.map((item) => item.file), ...incoming]);
    if (invalid) { setError(invalid); return; }
    setError(null);
    publish([...current.current, ...incoming.map((file) => ({ file, status: "queued" as const }))]);
    void process();
  }
  function retry(file: File) {
    if (current.current.find((item) => item.file === file)?.status !== "failed") return;
    update(file, { status: "queued", error: undefined });
    void process();
  }
  async function remove(file: File) {
    const item = current.current.find((entry) => entry.file === file);
    if (!item || ["processing", "removing"].includes(item.status)) return;
    if (item.status !== "ready") { publish(current.current.filter((entry) => entry.file !== file)); return; }
    if (working.current) return;
    working.current = true;
    update(file, { status: "removing", error: undefined });
    try {
      const resource = resources.current.find((entry) => entry.type === "raw" && entry.location.split("/").at(-1) === file.name);
      if (!resource) throw new Error("Source is unavailable. Open the workspace to refresh.");
      const result = await removeSessionFile(await getSessionId(), resource.id);
      resources.current = result.resources;
      publish(current.current.filter((entry) => entry.file !== file));
      if (mounted.current) onChanged?.(result.resources);
    } catch (cause) {
      update(file, { status: "ready", error: cause instanceof Error ? cause.message : "Failed to remove source" });
    } finally { working.current = false; void process(); }
  }
  return { items, error, add, retry, remove,
    forget: (name: string) => publish(current.current.filter((item) => item.file.name !== name)),
    busy: items.some((item) => ["queued", "processing", "removing"].includes(item.status)),
    ready: items.length > 0 && items.every((item) => item.status === "ready"),
  };
}
