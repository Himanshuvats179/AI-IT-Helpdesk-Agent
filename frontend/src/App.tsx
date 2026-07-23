import { useCallback, useEffect, useState } from "react";
import { api } from "./api/client";
import type { AppConfig, Ticket } from "./api/types";
import { TicketDetail } from "./components/TicketDetail";
import { TicketIntake } from "./components/TicketIntake";
import { TicketList } from "./components/TicketList";

export function App() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const loadTickets = useCallback(async () => {
    try {
      const page = await api.listTickets();
      setTickets(page.items);
    } catch {
      /* backend not up yet */
    }
  }, []);

  const handleCreated = useCallback(
    (id: string) => {
      setSelectedId(id);
      loadTickets();
    },
    [loadTickets]
  );

  useEffect(() => {
    api.getConfig().then(setConfig).catch(() => setConfig(null));
  }, []);

  useEffect(() => {
    loadTickets();
    const id = setInterval(loadTickets, 3000);
    return () => clearInterval(id);
  }, [loadTickets]);

  return (
    <div className="app">
      <div className="topbar">
        <h1>🛠️ AI IT Helpdesk Agent</h1>
        <span className="spacer" />
        {config && (
          <span className="meta">
            model: <b>{config.model}</b> ·{" "}
            {config.llm_configured ? "LLM ready" : "LLM not configured"} · auto ≥{" "}
            {Math.round(config.confidence_auto_threshold * 100)}%
          </span>
        )}
      </div>

      {config && !config.llm_configured && (
        <div className="banner warn" style={{ margin: 0, borderRadius: 0 }}>
          ⚠ ANTHROPIC_API_KEY is not set — the agent cannot run. Set it in <code>backend/.env</code>{" "}
          (and ANTHROPIC_BASE_URL for Azure/Foundry), then restart the backend.
        </div>
      )}

      <div className="layout">
        <div className="sidebar">
          <TicketIntake onCreated={handleCreated} />
          <div className="section" style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
            <h2>Tickets ({tickets.length})</h2>
            <TicketList tickets={tickets} selectedId={selectedId} onSelect={setSelectedId} />
          </div>
        </div>

        <div className="main">
          {selectedId ? (
            <TicketDetail key={selectedId} ticketId={selectedId} config={config} onChanged={loadTickets} />
          ) : (
            <div className="empty">Select or create a ticket to watch the agent work.</div>
          )}
        </div>
      </div>
    </div>
  );
}
