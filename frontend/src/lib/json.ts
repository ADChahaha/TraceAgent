export type JsonObject = Record<string, unknown>;

export interface JsonParseSuccess {
  ok: true;
  value: JsonObject;
}

export interface JsonParseFailure {
  ok: false;
  error: string;
}

export type JsonParseResult = JsonParseSuccess | JsonParseFailure;

export function parseJsonObject(input: string, fieldName: string): JsonParseResult {
  try {
    const parsed = JSON.parse(input);
    if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
      return { ok: false, error: `${fieldName} must be a valid JSON object` };
    }
    return { ok: true, value: parsed as JsonObject };
  } catch {
    return { ok: false, error: `${fieldName} must be a valid JSON object` };
  }
}

export function stringifyValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "string") {
    return value;
  }
  return JSON.stringify(value);
}
