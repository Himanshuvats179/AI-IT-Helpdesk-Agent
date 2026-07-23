export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge ${status}`}>{status.replace(/_/g, " ")}</span>;
}

export function PriorityBadge({ priority }: { priority: string | null }) {
  if (!priority) return null;
  return <span className={`badge ${priority.toLowerCase()}`}>{priority}</span>;
}

export function ConfidenceBadge({
  value,
  zone,
}: {
  value: number | null;
  zone: string | null;
}) {
  if (value == null) return <span className="pill">no score yet</span>;
  const cls = value >= 0.85 ? "conf-high" : value >= 0.7 ? "conf-mid" : "conf-low";
  return (
    <span className={`conf-badge ${cls}`}>
      {(value * 100).toFixed(0)}%{zone ? ` · ${zone.replace(/_/g, " ")}` : ""}
    </span>
  );
}

export function Flags({
  injection,
  security,
}: {
  injection: boolean;
  security: boolean;
}) {
  return (
    <>
      {injection && <span className="badge flag">injection</span>}
      {security && <span className="badge flag">security</span>}
    </>
  );
}
