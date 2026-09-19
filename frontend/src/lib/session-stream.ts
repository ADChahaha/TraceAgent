import type { SessionFrame } from "@/lib/session-types";

export async function consumeSessionStream(
  response: Response,
  onFrame: (frame: SessionFrame) => boolean | void,
  signal?: AbortSignal,
): Promise<void> {
  if (!response.body) throw new Error("The event stream has no body");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const abort = () => { void reader.cancel().catch(() => undefined); };
  signal?.addEventListener("abort", abort, { once: true });
  if (signal?.aborted) abort();
  let buffer = "";
  function dispatch(block: string) {
    let event = "";
    const data: string[] = [];
    for (const line of block.split(/\r?\n/)) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
    }
    if (event !== "session.snapshot" && event !== "session.event") return false;
    return onFrame({ event, data: JSON.parse(data.join("\n")) } as SessionFrame) === true;
  }
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (signal?.aborted) return;
      buffer += decoder.decode(value, { stream: !done });
      let separator: RegExpExecArray | null;
      while ((separator = /\r?\n\r?\n/.exec(buffer))) {
        const block = buffer.slice(0, separator.index);
        buffer = buffer.slice(separator.index + separator[0].length);
        if (dispatch(block)) return;
      }
      if (done) return;
    }
  } finally {
    signal?.removeEventListener("abort", abort);
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}
