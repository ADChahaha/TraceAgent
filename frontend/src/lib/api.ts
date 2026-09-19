import type { DocumentContent, DocumentEntry, FullDocument, SessionResource } from "@/lib/session-types";

export class ApiError extends Error {
  constructor(message: string, public readonly status: number, public readonly payload: unknown) {
    super(message);
    this.name = "ApiError";
  }
}

const sessionPath = (id: string) => `/api/backend/chat/sessions/${encodeURIComponent(id)}`;
const jsonBody = (value: unknown): RequestInit => ({
  method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(value),
});

async function checkedFetch(path: string, init?: RequestInit): Promise<Response> {
  const response = await fetch(path, { ...init, cache: "no-store" });
  if (!response.ok) {
    const text = await response.text();
    let payload: unknown = text;
    try { payload = JSON.parse(text); } catch { /* 非 JSON 错误保留原文。 */ }
    const detail = payload && typeof payload === "object" && "detail" in payload ? payload.detail : text;
    throw new ApiError(typeof detail === "string" ? detail : response.statusText || "Request failed", response.status, payload);
  }
  return response;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  return (await checkedFetch(path, init)).json() as Promise<T>;
}

async function requestStream(path: string, init?: RequestInit): Promise<Response> {
  const response = await checkedFetch(path, init);
  if (!response.headers.get("content-type")?.includes("text/event-stream")) {
    await response.body?.cancel();
    throw new Error("Expected an event stream");
  }
  return response;
}

export function createSession() {
  return requestJson<{ session_id: string }>("/api/backend/chat/sessions", { method: "POST" });
}

export interface SessionSummary { id: string; status: string; updated_at: string; active_turn_id: string | null }

export function listSessions() {
  return requestJson<{ sessions: SessionSummary[] }>("/api/backend/chat/sessions");
}

export function uploadSessionFiles(id: string, files: File[]) {
  const body = new FormData();
  files.forEach((file) => body.append("files", file));
  return requestJson<{ resources: SessionResource[] }>(`${sessionPath(id)}/files`, { method: "POST", body });
}

export function removeSessionFile(id: string, resourceId: string) {
  return requestJson<{ resources: SessionResource[] }>(sessionFileUrl(id, resourceId), { method: "DELETE" });
}

export function sessionFileUrl(id: string, resourceId: string) {
  return `${sessionPath(id)}/files/${encodeURIComponent(resourceId)}`;
}

export function openCompletion(id: string, content: string, signal?: AbortSignal) {
  return requestStream("/api/backend/chat/completion", { ...jsonBody({ session_id: id, content }), signal });
}

export function openResume(id: string, signal?: AbortSignal) {
  return requestStream(`/api/backend/resume?${new URLSearchParams({ session_id: id })}`, { signal });
}

export function cancelCompletion(id: string, turnId: string) {
  return requestJson<{ status: string }>("/api/backend/cancel", jsonBody({ session_id: id, turn_id: turnId }));
}

export function listSessionDocuments(id: string) {
  return requestJson<{ documents: DocumentEntry[] }>(`${sessionPath(id)}/documents`);
}

export function readSessionDocument(id: string, key: string) {
  return requestJson<DocumentContent>(`${sessionPath(id)}/documents/content?${new URLSearchParams({ key })}`);
}

export function readSessionBlock(id: string, key: string) {
  return requestJson<DocumentContent>(`${sessionPath(id)}/blocks?${new URLSearchParams({ key })}`);
}

export function readFullDocument(id: string, key: string) {
  return requestJson<FullDocument>(`${sessionPath(id)}/documents/full?${new URLSearchParams({ key })}`);
}
