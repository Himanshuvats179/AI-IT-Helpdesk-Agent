import { useState } from "react";
import { api } from "../api/client";
import type { AppConfig } from "../api/types";

export function VerifyPanel({
  ticketId,
  config,
  onDone,
}: {
  ticketId: string;
  config: AppConfig | null;
  onDone: () => void;
}) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.verify(ticketId, code.trim());
      setCode("");
      onDone();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card" style={{ borderColor: "var(--amber)" }}>
      <h3>Identity verification required</h3>
      <p className="muted">
        A one-time code was sent to the requester's registered factor (out-of-band).
        Enter it to authorize the privileged action.
      </p>
      {config?.otp_demo_enabled && (
        <div className="banner warn">Demo mode: the code is <b>123456</b>.</div>
      )}
      <div className="inline">
        <input
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder="Enter OTP code"
          onKeyDown={(e) => e.key === "Enter" && submit()}
        />
        <button className="primary" disabled={busy || !code.trim()} onClick={submit}>
          Verify
        </button>
      </div>
      {error && <div className="error-text" style={{ marginTop: 8 }}>{error}</div>}
    </div>
  );
}
