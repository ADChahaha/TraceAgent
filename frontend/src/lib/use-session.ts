"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, cancelCompletion, openCompletion, openResume } from "@/lib/api";
import { applySessionEvent, isTerminal } from "@/lib/session-state";
import { consumeSessionStream } from "@/lib/session-stream";
import { rememberSession } from "@/lib/session-store";
import type { SessionSnapshot } from "@/lib/session-types";

type Connection = "loading" | "live" | "idle" | "reconnecting" | "error";

export function useSession(sessionId: string) {
  const [snapshot, setSnapshot] = useState<SessionSnapshot | null>(null);
  const [connection, setConnection] = useState<Connection>("loading");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const state = useRef<SessionSnapshot | null>(null);
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const retry = useRef<ReturnType<typeof setTimeout> | null>(null);
  const locked = useRef(false);
  const cancelLock = useRef(false);

  const disconnect = useCallback(() => {
    generation.current += 1;
    controller.current?.abort();
    if (retry.current) clearTimeout(retry.current);
  }, []);

  const connect = useCallback((content?: string) => {
    disconnect();
    const version = generation.current;
    const abort = new AbortController();
    controller.current = abort;
    let failures = 0;
    const current = () => generation.current === version && !abort.signal.aborted;
    setConnection(content ? "live" : "loading");
    setError(null);
    async function read(question?: string): Promise<void> {
      let receivedSnapshot = false;
      try {
        const response = question === undefined
          ? await openResume(sessionId, abort.signal)
          : await openCompletion(sessionId, question, abort.signal);
        if (!current()) { await response.body?.cancel(); return; }
        await consumeSessionStream(response, (frame) => {
          if (!current()) return true;
          if (frame.event === "session.snapshot") {
            if (frame.data.session_id !== sessionId) throw new Error("Unexpected session snapshot");
            receivedSnapshot = true;
            state.current = frame.data;
            locked.current = false;
            setPending(null);
          } else {
            if (!receivedSnapshot || !state.current) throw new Error("Missing session snapshot");
            state.current = applySessionEvent(state.current, frame.data);
          }
          const next = state.current!;
          setSnapshot(next);
          const done = !next.state.active_turn_id;
          setConnection(done ? "idle" : "live");
          setError(null);
          if (frame.event === "session.snapshot" || done) rememberSession(sessionId, next);
          return done;
        }, abort.signal);
        if (current() && (!receivedSnapshot || state.current?.state.active_turn_id)) throw new Error("Stream interrupted");
      } catch (cause) {
        if (!current()) return;
        const message = cause instanceof Error ? cause.message : "Connection failed";
        setError(message);
        if (cause instanceof ApiError && [400, 404, 413, 422].includes(cause.status)) {
          locked.current = false;
          setPending(null);
          setConnection("error");
          return;
        }
        setConnection("reconnecting");
        // 创建结果不确定时只恢复快照，绝不自动重发问题。
        retry.current = setTimeout(() => { if (current()) void read(); }, Math.min(1000 * 2 ** failures++, 10000));
      }
    }
    void read(content);
  }, [disconnect, sessionId]);

  useEffect(() => {
    state.current = null;
    locked.current = false;
    cancelLock.current = false;
    // 路由变更清空本地投影，服务端轮次通过恢复流继续。
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSnapshot(null);
    setPending(null);
    setCancelling(false);
    connect();
    return disconnect;
  }, [connect, disconnect]);

  function send(content: string) {
    if (!content.trim() || locked.current || state.current?.state.active_turn_id) return;
    locked.current = true;
    setPending(content.trim());
    connect(content.trim());
  }

  async function cancel() {
    const turnId = state.current?.state.active_turn_id;
    if (!turnId || cancelLock.current) return;
    const version = generation.current;
    cancelLock.current = true;
    setCancelling(true);
    try {
      const result = await cancelCompletion(sessionId, turnId);
      if (generation.current !== version || !state.current) return;
      if (isTerminal(result.status)) {
        state.current = applySessionEvent(state.current, { turn_id: turnId, type: `turn.${result.status}`, payload: {} });
        setSnapshot(state.current);
        rememberSession(sessionId, state.current);
        if (!state.current.state.active_turn_id) { disconnect(); setConnection("idle"); }
      }
    } catch (cause) {
      if (generation.current === version) setError(cause instanceof Error ? cause.message : "Failed to cancel");
    } finally {
      cancelLock.current = false;
      setCancelling(false);
    }
  }

  return { snapshot: snapshot?.session_id === sessionId ? snapshot : null, connection, error, pending, cancelling,
    running: Boolean(snapshot?.session_id === sessionId && snapshot.state.active_turn_id) || pending !== null,
    send, cancel, refresh: connect };
}
