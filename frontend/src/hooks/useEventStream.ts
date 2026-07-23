import { useEffect, useRef, useState } from "react";
import type { AgentEvent } from "../api/types";

const EVENT_TYPES = [
  "run_started",
  "phase",
  "thought",
  "tool_call",
  "tool_result",
  "policy",
  "state_change",
  "confidence",
  "escalated",
  "resolved",
  "awaiting",
  "error",
  "run_finished",
];

/**
 * Subscribe to the live agent-trace SSE for a ticket. Returns the accumulated,
 * sequence-deduplicated event list and a connection flag. A `bump` value lets the
 * caller force a reconnect (e.g. after submitting an action that starts a new run).
 */
const MAX_BACKOFF_MS = 30_000;

export function useEventStream(ticketId: string | null, bump = 0) {
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const seen = useRef<Set<number>>(new Set());

  useEffect(() => {
    if (!ticketId) return;
    setEvents([]);
    seen.current = new Set();

    let source: EventSource | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;
    let cancelled = false;

    const handler = (e: MessageEvent) => {
      try {
        const parsed = JSON.parse(e.data) as AgentEvent;
        // Use a strict null check: seq === 0 is a valid id and must dedupe too.
        if (parsed.seq != null) {
          if (seen.current.has(parsed.seq)) return;
          seen.current.add(parsed.seq);
        }
        setEvents((prev) => [...prev, parsed]);
      } catch {
        /* ignore malformed */
      }
    };

    const connect = () => {
      if (cancelled) return;
      const es = new EventSource(`/v1/tickets/${ticketId}/stream`);
      source = es;
      es.onopen = () => {
        attempt = 0;
        setConnected(true);
      };
      es.onerror = () => {
        setConnected(false);
        // While readyState === CONNECTING the browser is already retrying; only
        // when it gives up (CLOSED) do we reconnect ourselves, with backoff, so
        // a downed backend can't trigger a tight reconnect loop.
        if (es.readyState === EventSource.CLOSED) {
          es.close();
          const delay = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** attempt);
          attempt += 1;
          reconnectTimer = setTimeout(connect, delay);
        }
      };
      EVENT_TYPES.forEach((t) => es.addEventListener(t, handler as EventListener));
    };

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (source) {
        EVENT_TYPES.forEach((t) => source!.removeEventListener(t, handler as EventListener));
        source.close();
      }
      setConnected(false);
    };
  }, [ticketId, bump]);

  return { events, connected };
}
