const TOOL_LABELS: Record<string, { idle: string; running: string }> = {
  ls: { idle: "Browse files", running: "Browsing files" },
  read: { idle: "Read passage", running: "Reading passage" },
  grep: { idle: "Keyword search", running: "Searching keywords" },
  search_embedding: { idle: "Semantic search", running: "Searching semantically" },
};

const FALLBACK_LABEL = { idle: "Document lookup", running: "Inspecting sources" };

export function formatToolAction(name: string | undefined, status: string): string {
  const key = (name ?? "").trim().toLowerCase();
  const entry = TOOL_LABELS[key] ?? FALLBACK_LABEL;
  if (status === "running") {
    return entry.running;
  }
  if (status === "failed") {
    return `${entry.idle} (unavailable)`;
  }
  if (status === "interrupted") {
    return `${entry.idle} (interrupted)`;
  }
  return entry.idle;
}
