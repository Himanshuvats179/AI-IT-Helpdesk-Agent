import type { Ticket } from "../api/types";
import { ConfidenceBadge, Flags, PriorityBadge, StatusBadge } from "./Badges";

export function TicketList({
  tickets,
  selectedId,
  onSelect,
}: {
  tickets: Ticket[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="ticket-list">
      {tickets.length === 0 && <div className="empty">No tickets yet.</div>}
      {tickets.map((t) => (
        <div
          key={t.id}
          role="button"
          tabIndex={0}
          aria-pressed={t.id === selectedId}
          className={`ticket-card ${t.id === selectedId ? "active" : ""}`}
          onClick={() => onSelect(t.id)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              onSelect(t.id);
            }
          }}
        >
          <div className="subject">{t.subject}</div>
          <div className="row">
            <StatusBadge status={t.status} />
            <PriorityBadge priority={t.priority} />
            <Flags injection={t.injection_flag} security={t.security_label} />
            <ConfidenceBadge value={t.confidence} zone={null} />
          </div>
        </div>
      ))}
    </div>
  );
}
