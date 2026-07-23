import type { AgentEvent } from "../api/types";

const ICONS: Record<string, string> = {
  run_started: "▶",
  phase: "◆",
  thought: "💭",
  tool_call: "🔧",
  tool_result: "📦",
  policy: "🛡️",
  state_change: "↪",
  confidence: "🎯",
  escalated: "🚨",
  resolved: "✅",
  awaiting: "⏳",
  error: "⚠️",
  run_finished: "■",
};

function renderBody(e: AgentEvent) {
  const d = e.data || {};
  switch (e.type) {
    case "phase":
      return (
        <span>
          phase: <code>{d.phase}</code>
          {d.retrieval && (
            <> · KB match: <code>{d.retrieval.confidence}</code> ({(d.retrieval.kb_ids || []).join(", ") || "none"})</>
          )}
        </span>
      );
    case "thought":
      return <span>{d.text || d.message}</span>;
    case "tool_call":
      return (
        <span>
          calling <code>{d.tool}</code> {d.args && <span className="muted">{JSON.stringify(d.args)}</span>}
        </span>
      );
    case "tool_result":
      return (
        <span className={d.is_error ? "error-text" : ""}>
          <code>{d.tool}</code> → {d.is_error ? "error" : "ok"}{" "}
          <span className="muted">{JSON.stringify(d.output)?.slice(0, 160)}</span>
        </span>
      );
    case "policy":
      return (
        <span>
          policy on <code>{d.tool}</code>: <b>{d.decision}</b> <span className="muted">({d.rule}) {d.reason}</span>
        </span>
      );
    case "confidence":
      return (
        <span>
          confidence — model {Math.round((d.model ?? 0) * 100)}% → calibrated{" "}
          <b>{Math.round((d.calibrated ?? 0) * 100)}%</b> · {d.zone}
          {d.reasons?.length ? <span className="muted"> [{d.reasons.join(", ")}]</span> : null}
        </span>
      );
    case "state_change":
      return <span>state → <code>{d.status}</code>{d.priority ? ` (${d.priority})` : ""}</span>;
    case "escalated":
      return <span>escalated to <code>{d.queue}</code> — {d.reason}</span>;
    case "resolved":
      return <span>resolved at {Math.round((d.confidence ?? 0) * 100)}% · cited {(d.cited_kb_ids || []).join(", ")}</span>;
    case "awaiting":
      return <span>awaiting <code>{d.awaiting}</code>{d.factor ? ` (${d.factor})` : ""}</span>;
    case "run_started":
      return <span>run started · {d.trigger} (attempt {d.attempt})</span>;
    case "run_finished":
      return <span>run finished · {d.outcome}{d.reason ? ` (${d.reason})` : ""}</span>;
    case "error":
      return <span className="error-text">{d.message || JSON.stringify(d)}</span>;
    default:
      return <span className="muted">{JSON.stringify(d)}</span>;
  }
}

export function AgentTrace({
  events,
  connected,
}: {
  events: AgentEvent[];
  connected: boolean;
}) {
  return (
    <div className="card">
      <h3>
        Agent trace{" "}
        <span className="inline" style={{ float: "right" }}>
          <span className={`dot ${connected ? "on" : "off"}`} />
          <span className="pill">{connected ? "live" : "idle"}</span>
        </span>
      </h3>
      {events.length === 0 ? (
        <div className="muted">No activity yet. The agent's reasoning will stream here in real time.</div>
      ) : (
        <div className="trace">
          {events.map((e) => (
            <div key={e.seq} className={`trace-row ${e.type}`}>
              <span className="icon">{ICONS[e.type] ?? "•"}</span>
              <div className="body">
                <div className="label">{e.type.replace(/_/g, " ")}</div>
                {renderBody(e)}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
