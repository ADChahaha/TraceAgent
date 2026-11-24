export type ErrorContext = "upload" | "remove" | "chat" | "session" | "document" | "general";

const KNOWN_EXACT_MESSAGES: Record<string, string> = {
  backend_restarted: "This response was interrupted because the service restarted. You can ask again.",
  storage_failure: "We couldn't save the conversation state. Please try again.",
  "backend unavailable": "Unable to reach the workspace service. Check that it is running and try again.",
  "stream interrupted": "Connection to the live response was interrupted. Reconnecting...",
  "expected an event stream": "Received an unexpected response from the server. Please try again.",
};

const NETWORK_ERROR_PATTERN = /\b(failed to fetch|load failed|networkerror|network request failed|fetch failed)\b/i;

// 识别可能从旧会话或未预期通道漏出的底层技术细节、堆栈、HTML 错误页或内部中文错误。
const INTERNAL_DETAIL_PATTERN =
  /(?:grpc|ipv4:|ipv6:|127\.0\.0\.1|localhost:\d+|traceback|httpx|socksio|sqlite|econnrefused|connection refused|<!doctype|<html|pydantic|validation error for|errno|statuscode|[\u4e00-\u9fff])/i;

const CONTEXT_FALLBACKS: Record<ErrorContext, string> = {
  upload: "We couldn't process this document right now. Please try again.",
  remove: "We couldn't remove this file right now. Please try again.",
  chat: "Unable to generate a response right now. Please try again.",
  session: "Unable to connect to this workspace right now. Please try again.",
  document: "We couldn't load this document right now. Please try again.",
  general: "Something went wrong. Please try again.",
};

function classifyTechnicalError(lowered: string, context: ErrorContext): string {
  if (/(unavailable|connection refused|failed to connect|econnrefused)/.test(lowered)) {
    if (context === "upload" || context === "remove" || context === "document") {
      return "Document processing is temporarily unavailable. Please try again in a moment.";
    }
    if (context === "chat") {
      return "The assistant service is temporarily unavailable. Please try again in a moment.";
    }
    return "Unable to reach the workspace service. Please try again in a moment.";
  }
  if (/(deadline_exceeded|timed out|timeout)/.test(lowered)) {
    if (context === "upload" || context === "document") {
      return "Document processing timed out. Try a smaller file or retry.";
    }
    return "The request timed out before an answer was ready. Please try again.";
  }
  if (/(resource_exhausted|rate limit|too many requests|\b429\b|overloaded)/.test(lowered)) {
    return "The assistant is busy right now. Please wait a moment and try again.";
  }
  if (/(unauthorized|authentication|api key|\b401\b|\b403\b)/.test(lowered)) {
    return "The model service rejected authentication. Check the server configuration and try again.";
  }
  if (/(context length|maximum context|too many tokens)/.test(lowered)) {
    return "This conversation exceeded the model's context limit. Start a new workspace or shorten your question.";
  }
  if (/invalid_argument/.test(lowered)) {
    if (context === "upload" || context === "document") {
      return "This document could not be read. Check that the file is a valid PDF or DOCX and try again.";
    }
    return "The request is invalid. Please check your input and try again.";
  }
  if (/not_found/.test(lowered)) {
    if (context === "document") {
      return "The requested document content is no longer available.";
    }
    return "The requested resource could not be found.";
  }
  return CONTEXT_FALLBACKS[context];
}

function fallbackByStatus(status: number, context: ErrorContext): string {
  if (status === 413) return "This upload exceeds the size limit.";
  if (status === 404) {
    return context === "document"
      ? "The requested document could not be found in this workspace."
      : "This workspace or resource could not be found.";
  }
  if (status === 409) return "This workspace is busy right now. Please try again in a moment.";
  if (status === 422) return "The request is invalid. Please check your input and try again.";
  if (status === 502 || status === 503 || status === 504) {
    return classifyTechnicalError("unavailable", context);
  }
  return CONTEXT_FALLBACKS[context];
}

function readApiStatus(input: unknown): number | undefined {
  if (typeof input === "object" && input !== null && "status" in input && typeof (input as { status?: unknown }).status === "number") {
    return (input as { status: number }).status;
  }
  return undefined;
}

export function formatUserError(input: unknown, context: ErrorContext = "general"): string {
  const raw = (input instanceof Error ? input.message : typeof input === "string" ? input : "").trim();
  const status = readApiStatus(input);

  if (!raw) {
    return status !== undefined ? fallbackByStatus(status, context) : CONTEXT_FALLBACKS[context];
  }

  const lowered = raw.toLowerCase();
  if (lowered in KNOWN_EXACT_MESSAGES) {
    return KNOWN_EXACT_MESSAGES[lowered];
  }
  if (NETWORK_ERROR_PATTERN.test(raw)) {
    return "Unable to reach the workspace service. Check your connection and try again.";
  }
  if (INTERNAL_DETAIL_PATTERN.test(raw)) {
    return classifyTechnicalError(lowered, context);
  }
  return raw;
}
