import type {
  AgentRun,
  AppConfig,
  Escalation,
  Page,
  Ticket,
  TicketDetail,
} from "./types";

// Operator identity used for HITL actions. Configurable per-environment via
// VITE_OPERATOR_ID rather than hardcoded at each call site.
const OPERATOR_ID = import.meta.env.VITE_OPERATOR_ID ?? "operator@corp.com";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      detail = body?.error?.message ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

export const api = {
  getConfig: () => request<AppConfig>("/v1/config"),

  listTickets: (params: { requester?: string; status?: string } = {}) => {
    const q = new URLSearchParams();
    if (params.requester) q.set("requester", params.requester);
    if (params.status) q.set("status", params.status);
    q.set("limit", "100");
    return request<Page<Ticket>>(`/v1/tickets?${q.toString()}`);
  },

  getTicket: (id: string) => request<TicketDetail>(`/v1/tickets/${id}`),

  getRuns: (id: string) => request<AgentRun[]>(`/v1/tickets/${id}/runs`),

  createTicket: (body: string, requester_upn?: string) =>
    request<{ ticket_id: string; status: string; duplicate_of: string | null }>(
      "/v1/tickets",
      { method: "POST", body: JSON.stringify({ body, requester_upn }) }
    ),

  sendMessage: (id: string, body: string) =>
    request<{ status: string }>(`/v1/tickets/${id}/messages`, {
      method: "POST",
      body: JSON.stringify({ body }),
    }),

  verify: (id: string, code: string) =>
    request<{ status: string }>(`/v1/tickets/${id}/verify`, {
      method: "POST",
      body: JSON.stringify({ code }),
    }),

  approve: (id: string, approve: boolean, operator_id = OPERATOR_ID, note?: string) =>
    request<{ status: string }>(`/v1/tickets/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({ approve, operator_id, note }),
    }),

  hitl: (
    id: string,
    action: string,
    extra: { operator_id?: string; message?: string; note?: string } = {}
  ) =>
    request<{ status: string }>(`/v1/tickets/${id}/hitl`, {
      method: "POST",
      body: JSON.stringify({ action, operator_id: OPERATOR_ID, ...extra }),
    }),

  getEscalation: (id: string) =>
    request<Escalation | null>(`/v1/tickets/${id}/escalation`),
};
