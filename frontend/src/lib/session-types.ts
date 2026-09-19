export interface SessionResource {
  id: string;
  type: "documents" | "index" | "raw";
  location: string;
  size_bytes?: number;
}

export interface SessionItem {
  id: string;
  kind: "user" | "assistant" | "tool" | "retry";
  status: string;
  text?: string;
  name?: string;
  tool_calls?: unknown[];
  detail?: Record<string, unknown>;
}

export interface SessionTurn {
  id: string;
  status: string;
  items: SessionItem[];
  error: string | null;
}

export interface SessionSnapshot {
  session_id: string;
  state: {
    status: string;
    active_turn_id: string | null;
    resources: SessionResource[];
    turns: SessionTurn[];
  };
}

export interface SessionEvent {
  turn_id: string;
  type: string;
  payload: Record<string, unknown>;
}

export type SessionFrame =
  | { event: "session.snapshot"; data: SessionSnapshot }
  | { event: "session.event"; data: SessionEvent };

export interface DocumentEntry { key: string; size: number }
export interface DocumentContent { key: string; text: string; found?: boolean }

export interface FullDocument { key: string; blocks: DocumentContent[] }
