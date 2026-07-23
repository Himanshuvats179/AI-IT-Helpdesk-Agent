export interface Message {
  id: string;
  role: "user" | "agent" | "system" | "human";
  body: string;
  author: string | null;
  created_at: string;
}

export interface PendingApproval {
  tool: string;
  args?: Record<string, unknown>;
  reason?: string;
  rule?: string;
  run_id?: string;
}

export interface AgentState {
  pending_approval?: PendingApproval;
  [key: string]: unknown;
}

export interface HandoverPayload {
  why_escalated?: string;
  reason_code?: string;
  recommended_next_steps?: string[];
  current_hypothesis?: string | null;
  [key: string]: unknown;
}

export interface Ticket {
  id: string;
  requester_upn: string;
  subject: string;
  status: string;
  category: string | null;
  urgency: string | null;
  impact: string | null;
  priority: string | null;
  sentiment: string | null;
  language: string;
  model_confidence: number | null;
  confidence: number | null;
  confidence_zone: string | null;
  security_label: boolean;
  injection_flag: boolean;
  duplicate_of: string | null;
  cost_cents: number;
  attempt: number;
  entities: Record<string, unknown>;
  resolution: Record<string, unknown>;
  agent_state: AgentState;
  sla_due_at: string | null;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
  closed_at: string | null;
}

export interface TicketDetail extends Ticket {
  messages: Message[];
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface ToolCall {
  id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  output: Record<string, unknown>;
  is_error: boolean;
  policy_decision: string | null;
  latency_ms: number;
  created_at: string;
}

export interface AgentRun {
  id: string;
  ticket_id: string;
  attempt: number;
  trigger: string;
  status: string;
  model: string | null;
  steps: number;
  input_tokens: number;
  output_tokens: number;
  cost_cents: number;
  outcome: string | null;
  final_confidence: number | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
  tool_calls: ToolCall[];
}

export interface Escalation {
  id: string;
  ticket_id: string;
  run_id: string | null;
  reason: string;
  queue: string;
  model_self_confidence: number | null;
  calibrated_confidence: number | null;
  payload: HandoverPayload;
  status: string;
  assignee: string | null;
  created_at: string;
}

export interface AppConfig {
  app_name: string;
  model: string;
  llm_configured: boolean;
  confidence_auto_threshold: number;
  confidence_verify_threshold: number;
  followup_delay_seconds: number;
  otp_demo_enabled: boolean;
}

export interface AgentEvent {
  type: string;
  seq: number;
  data: Record<string, any>;
  run_id?: string | null;
}
