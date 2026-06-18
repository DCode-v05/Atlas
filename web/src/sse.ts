import { useStore } from "./store";
import { KNOWN_EVENTS } from "./types";

// Native EventSource: the stream is an unauthenticated same-origin GET, so no
// custom headers are needed. Named events are dispatched per type; ready/ping
// keep-alives are handled separately and never reach applyEvent.

let es: EventSource | null = null;
let pruneTimer: number | null = null;

export function connectSSE(): void {
  const { setConn } = useStore.getState();
  setConn("connecting");

  es?.close();
  es = new EventSource("/api/events");

  es.addEventListener("open", () => useStore.getState().setConn("live"));
  es.addEventListener("ready", () => useStore.getState().setConn("live"));
  es.addEventListener("error", () => useStore.getState().setConn("down"));

  const handle = (e: MessageEvent) => {
    try {
      const env = JSON.parse(e.data);
      useStore.getState().applyEvent(env);
    } catch (err) {
      // eslint-disable-next-line no-console
      console.warn("[atlas] failed to parse SSE payload", err);
    }
  };
  for (const name of KNOWN_EVENTS) es!.addEventListener(name, handle as EventListener);

  if (pruneTimer) clearInterval(pruneTimer);
  pruneTimer = window.setInterval(() => useStore.getState().pruneLinks(), 600);
}
