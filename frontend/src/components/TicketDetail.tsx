import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { AppConfig, Escalation, TicketDetail as TDetail } from "../api/types";
import { useEventStream } from "../hooks/useEventStream";
import { AgentTrace } from "./AgentTrace";
import { ConfidenceBadge, Flags, PriorityBadge, StatusBadge } from "./Badges";
import { Conversation } from "./Conversation";
import { HitlPanel } from "./HitlPanel";
import { VerifyPanel } from "./VerifyPanel";

const CLOSED = ["closed", "closed_no_response"];

export function TicketDetail({
  ticketId,
  config,
  onChanged,
}: {
  ticketId: string;
  config: AppConfig | null;
  onChanged: () => void;
}) {
  const [detail, setDetail] = useState<TDetail | null>(null);
  const [escalation, setEscalation] = useState<Escalation | null>(null);
  const [reply, setReply] = useState("");
  const [bump, setBump] = useState(0);
  const { events, connected } = useEventStream(ticketId, bump);

  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [ticket, esc] = await Promise.all([
        api.getTicket(ticketId),
        api.getEscalation(ticketId),
      ]);
      setDetail(ticket);
      setEscalation(esc);
      onChanged();
    } catch {
      /* transient */
    }
  }, [ticketId, onChanged]);

  // Debounced refresh that supersedes any pending one — used by both the
  // event-driven path and post-action callbacks, and cleaned up on unmount.
  const scheduleRefresh = useCallback(
    (delay = 400) => {
      if (refreshTimer.current) clearTimeout(refreshTimer.current);
      refreshTimer.current = setTimeout(() => {
        refreshTimer.current = null;
        refresh();
      }, delay);
    },
    [refresh]
  );

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Coalesce bursts of trace events into a single refetch (status likely
  // changed) instead of firing one request pair per event.
  useEffect(() => {
    if (events.length === 0) return;
    scheduleRefresh();
  }, [events.length, scheduleRefresh]);

  // backstop poll
  useEffect(() => {
    const id = setInterval(refresh, 3000);
    return () => clearInterval(id);
  }, [refresh]);

  // clear any pending debounced refresh on unmount
  useEffect(() => () => {
    if (refreshTimer.current) clearTimeout(refreshTimer.current);
  }, []);

  if (!detail) return <div className="empty">Loading…</div>;

  const sendReply = async () => {
    if (!reply.trim()) return;
    await api.sendMessage(ticketId, reply.trim());
    setReply("");
    setBump((b) => b + 1);
    scheduleRefresh(500);
  };

  const closed = CLOSED.includes(detail.status);

  return (
    <div>
      <div className="card">
        <h3>
          {detail.subject}{" "}
          <span style={{ float: "right" }} className="inline">
            <StatusBadge status={detail.status} />
            <PriorityBadge priority={detail.priority} />
            <Flags injection={detail.injection_flag} security={detail.security_label} />
          </span>
        </h3>
        <div className="kv">
          <span className="k">Ticket</span><span><code>{detail.id}</code></span>
          <span className="k">Requester</span><span>{detail.requester_upn}</span>
          <span className="k">Category</span><span>{detail.category ?? "—"}</span>
          <span className="k">Confidence</span>
          <span><ConfidenceBadge value={detail.confidence} zone={detail.confidence_zone} /></span>
          <span className="k">Cost</span><span>{detail.cost_cents.toFixed(2)}¢ · {detail.attempt} attempt(s)</span>
          {Object.keys(detail.entities || {}).length > 0 && (
            <>
              <span className="k">Entities</span>
              <span className="muted">{JSON.stringify(detail.entities)}</span>
            </>
          )}
        </div>
      </div>

      {detail.status === "awaiting_verification" && (
        <VerifyPanel ticketId={ticketId} config={config} onDone={() => { setBump((b) => b + 1); scheduleRefresh(500); }} />
      )}

      <HitlPanel
        ticket={detail}
        escalation={escalation}
        onAction={() => { setBump((b) => b + 1); scheduleRefresh(500); }}
      />

      <Conversation messages={detail.messages} />

      {!closed && (
        <div className="card">
          <h3>Reply as the user</h3>
          <div className="inline">
            <input
              value={reply}
              onChange={(e) => setReply(e.target.value)}
              placeholder="Type a reply (e.g. your OTP, 'yes it works', or more detail)…"
              onKeyDown={(e) => e.key === "Enter" && sendReply()}
            />
            <button className="primary" disabled={!reply.trim()} onClick={sendReply}>Send</button>
          </div>
        </div>
      )}

      <AgentTrace events={events} connected={connected} />
    </div>
  );
}
