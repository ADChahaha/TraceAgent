import type {
  AuditResult,
  Capabilities,
  TaskReplay,
  TaskCreated,
  TaskDetailData,
  TaskList,
  TaskResult,
  TaskSummary,
  TaskTrace
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
  return requestJson<TaskCreated>("/api/backend/tasks", {
    method: "POST",
    body: formData
  });
}

export async function listTasks(): Promise<TaskSummary[]> {
  const payload = await requestJson<TaskList>("/api/backend/tasks");
  return payload.tasks;
}

export async function getTaskSummary(taskId: string): Promise<TaskSummary> {
  return requestJson<TaskSummary>(`/api/backend/tasks/${encodeURIComponent(taskId)}`);
}

export async function getTaskResult(taskId: string): Promise<TaskResult> {
  return requestJson<TaskResult>(`/api/backend/tasks/${encodeURIComponent(taskId)}/result`);
}

export async function getTaskTrace(taskId: string): Promise<TaskTrace> {
  return requestJson<TaskTrace>(`/api/backend/tasks/${encodeURIComponent(taskId)}/trace`);
}

export async function getTaskReplay(taskId: string): Promise<TaskReplay> {
  return requestJson<TaskReplay>(`/api/backend/tasks/${encodeURIComponent(taskId)}/replay`);
}

export async function getTaskAudit(taskId: string): Promise<AuditResult> {
  return requestJson<AuditResult>(`/api/backend/tasks/${encodeURIComponent(taskId)}/audit`);
}

export async function loadTaskDetail(taskId: string): Promise<TaskDetailData> {
  const summary = await getTaskSummary(taskId);
  const [result, replay] = await Promise.all([
    optionalFetch(() => getTaskResult(taskId), summary.has_result !== false),
    optionalFetch(
      () => getTaskReplay(taskId),
      summary.has_trace !== false || summary.has_result !== false,
    )
  ]);

  return {
    summary,
    result,
    trace: null,
    replay,
    audit: null
  };
}

async function optionalFetch<T>(loader: () => Promise<T>, enabled: boolean): Promise<T | null> {
  if (!enabled) {
    return null;
  }
  try {
    return await loader();
  } catch (error) {
    if (
      error instanceof ApiError &&
      (error.status === 404 || error.status === 409 || error.status >= 500)
    ) {
      return null;
    }
    throw error;
  }
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
  return fallback || "请求失败";
}
