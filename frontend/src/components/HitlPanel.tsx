import { useState } from "react";
import { api } from "../api/client";
import type { Escalation, Ticket } from "../api/types";

export function HitlPanel({
  ticket,
  escalation,
  onAction,
}: {
  ticket: Ticket;
  escalation: Escalation | null;
  onAction: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await fn();
      setNote("");
      onAction();
    } finally {
      setBusy(false);
    }
  };

  const pendingApproval = ticket.agent_state?.pending_approval;

  return (
    <div className="card">
      <h3>Human-in-the-loop</h3>

      {ticket.status === "awaiting_approval" && pendingApproval && (
        <div className="banner warn">
          Approval requested for <b>{pendingApproval.tool}</b>
          {pendingApproval.args ? (
            <span className="muted"> {JSON.stringify(pendingApproval.args)}</span>
          ) : null}
          <div className="muted">{pendingApproval.reason}</div>
        </div>
      )}

      {escalation && (
        <div style={{ marginBottom: 12 }}>
          <div className="kv">
            <span className="k">Escalated</span>
            <span>{escalation.payload?.why_escalated ?? escalation.reason}</span>
            <span className="k">Queue</span>
            <span><code>{escalation.queue}</code></span>
            <span className="k">Model vs calibrated</span>
            <span>
              {pct(escalation.model_self_confidence)} → <b>{pct(escalation.calibrated_confidence)}</b>
            </span>
          </div>
          {escalation.payload?.recommended_next_steps?.length ? (
            <>
              <div className="label" style={{ marginTop: 8 }}>Recommended next steps</div>
              <ul className="steps">
                {escalation.payload.recommended_next_steps.map((s: string, i: number) => (
                  <li key={i}>{s}</li>
                ))}
              </ul>
            </>
          ) : null}
        </div>
      )}

      <input
        placeholder="Operator note / message…"
        value={note}
        onChange={(e) => setNote(e.target.value)}
      />
      <div className="row-actions">
        {ticket.status === "awaiting_approval" && (
          <>
            <button className="primary" disabled={busy} onClick={() => run(() => api.approve(ticket.id, true))}>
              Approve action
            </button>
            <button className="danger" disabled={busy} onClick={() => run(() => api.approve(ticket.id, false, undefined, note))}>
              Deny
            </button>
          </>
        )}
        <button className="ghost" disabled={busy} onClick={() => run(() => api.hitl(ticket.id, "take_over", { note }))}>
          Take over
        </button>
        <button className="ghost" disabled={busy} onClick={() => run(() => api.hitl(ticket.id, "force_resolve", { message: note || "Resolved by specialist." }))}>
          Force resolve
        </button>
        <button className="ghost" disabled={busy} onClick={() => run(() => api.hitl(ticket.id, "force_escalate", { note }))}>
          Force escalate
        </button>
        <button className="ghost" disabled={busy || !note.trim()} onClick={() => run(() => api.hitl(ticket.id, "reply", { message: note }))}>
          Reply as human
        </button>
      </div>
    </div>
  );
}

function pct(v: number | null | undefined) {
  return v == null ? "—" : `${Math.round(v * 100)}%`;
}
