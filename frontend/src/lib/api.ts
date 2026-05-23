import type {
  Capabilities,
  QaInputCreated,
  TaskCreated,
  TaskDetailData,
  TaskEvent,
  TaskList,
  TaskSummary,
} from "@/lib/types";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly payload: unknown
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function getCapabilities(): Promise<Capabilities> {
  return requestJson<Capabilities>("/api/backend/capabilities");
}

export async function createTask(formData: FormData): Promise<TaskCreated> {
  return requestJson<TaskCreated>("/api/backend/qa/tasks", {
    method: "POST",
    body: formData
  });
}

export async function listTasks(): Promise<TaskSummary[]> {
  const payload = await requestJson<TaskList>("/api/backend/qa/tasks");
  return payload.tasks;
}

export async function getTaskSummary(taskId: string): Promise<TaskSummary> {
  return requestJson<TaskSummary>(`/api/backend/qa/tasks/${encodeURIComponent(taskId)}`);
}

export async function createTaskInput(
  taskId: string,
  content: string,
  runOptions?: Record<string, unknown>
): Promise<QaInputCreated> {
  const body = runOptions === undefined ? { content } : { content, run_options: runOptions };
  return requestJson<QaInputCreated>(`/api/backend/qa/tasks/${encodeURIComponent(taskId)}/inputs`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body)
  });
}

export async function cancelTask(taskId: string): Promise<unknown> {
  return requestJson<unknown>(`/api/backend/qa/tasks/${encodeURIComponent(taskId)}/cancel`, {
    method: "POST"
  });
}

export function getTaskEventsUrl(taskId: string, afterSeq = 0): string {
  const params = new URLSearchParams({ after_seq: String(Math.max(0, afterSeq)) });
  return `/api/backend/qa/tasks/${encodeURIComponent(taskId)}/events?${params.toString()}`;
}

export function createTaskEventSource(taskId: string, afterSeq = 0): EventSource {
  if (typeof EventSource === "undefined") {
    return createNoopEventSource();
  }
  return new EventSource(getTaskEventsUrl(taskId, afterSeq));
}

export function parseTaskEventMessage(event: MessageEvent<string>): TaskEvent | null {
  try {
    return JSON.parse(event.data) as TaskEvent;
  } catch {
    return null;
  }
}

export async function loadTaskDetail(taskId: string): Promise<TaskDetailData> {
  const summary = await getTaskSummary(taskId);
  return {
    summary,
    result: null,
    trace: null,
    replay: null,
    audit: null
  };
}

async function requestJson<T>(input: string, init?: RequestInit): Promise<T> {
  const response = await fetch(input, {
    ...init,
    cache: "no-store"
  });
  const payload = await parseResponsePayload(response);
  if (!response.ok) {
    throw new ApiError(getErrorMessage(payload, response.statusText), response.status, payload);
  }
  return payload as T;
}

async function parseResponsePayload(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) {
    return null;
  }
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function getErrorMessage(payload: unknown, fallback: string): string {
  if (
    payload &&
    typeof payload === "object" &&
    "detail" in payload &&
    typeof payload.detail === "string"
  ) {
    return payload.detail;
  }
  return fallback || "Request failed";
}

function createNoopEventSource(): EventSource {
  return {
    close() {},
    addEventListener() {},
    removeEventListener() {},
    dispatchEvent() {
      return false;
    },
    onerror: null,
    onmessage: null,
    onopen: null,
    readyState: 2,
    url: "",
    withCredentials: false,
    CONNECTING: 0,
    OPEN: 1,
    CLOSED: 2,
  } as EventSource;
}
