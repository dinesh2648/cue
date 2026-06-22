export interface Meeting {
  id: string;
  title: string;
  platform: string;
  customer_company: string;
  customer_contact: string;
  rep_name: string;
  status: "scheduled" | "live" | "ended";
  crm_company_id: string | null;
  pack: string;
  created_at: string;
  ended_at: string | null;
}

export interface Segment {
  id: string;
  speaker: string;
  role: "customer" | "rep" | "system";
  text: string;
  ts: number;
}

export interface Source {
  label: string;
  type: "crm" | "document";
  detail: string;
  url: string;
}

export interface Action {
  label: string;
  type: string;
  [k: string]: unknown;
}

export interface Suggestion {
  id: string;
  intent_type: string;
  query_text: string;
  answer: string;
  evidence: string[];
  sources: Source[];
  actions: Action[];
  confidence: number;
  latency_ms: number;
  deep_latency_ms?: number;
  engine?: string;
  deep_pending?: boolean;
  created_at: string;
}

export interface Connector {
  provider: string;
  name: string;
  icon: string;
  category: string;
  description: string;
  oauth_available: boolean;
  oauth_mode: "live" | "demo";
  mcp_default: string;
  has_mcp: boolean;
  status: "connected" | "disconnected" | "error";
  account_label: string;
  error: string | null;
}

export interface Summary {
  executive_summary: string;
  key_decisions: string[];
  risks: string[];
  action_items: string[];
  customer_concerns: string[];
  follow_up_email: string;
}

export interface Metrics {
  meetings: number;
  suggestions: number;
  avg_latency_ms: number;
  p95_latency_ms: number;
  response_sla_ms: number;
  sla_compliance_pct: number;
}

export interface ProposedAction {
  id: string;
  meeting_id: string;
  pack: string;
  action_key: string;
  kind: string;
  title: string;
  payload: Record<string, unknown>;
  write: boolean;
  autonomy: string;
  status: "proposed" | "executed" | "rejected" | "failed";
  approver: string | null;
  result: Record<string, unknown>;
  error: string | null;
  created_at: string;
  decided_at: string | null;
}

export interface PlanInfo {
  key: string;
  name: string;
  price_monthly: number | null;
  meetings_per_month: number | null;
  max_connectors: number | null;
  seats: number | null;
  recall: boolean;
  sso: boolean;
  blurb: string;
}

export interface Usage {
  plan: string;
  plan_name: string;
  meetings_used: number;
  meetings_limit: number | null;
  connectors_used: number;
  connectors_limit: number | null;
  seats: number;
  features: { recall: boolean; sso: boolean };
  billing_enabled: boolean;
}

export interface BillingInfo {
  org: { id: string; name: string; plan: string; role: string };
  usage: Usage;
  plans: PlanInfo[];
}

export interface OrgInfo {
  id: string;
  name: string;
  plan: string;
  your_role: string;
  members: { id: string; email: string; name: string; role: string }[];
}

export type WSEvent =
  | { type: "transcript"; data: Segment }
  | { type: "intent"; data: { intent_type: string; family: string; confidence: number; query_text: string; actionable: boolean } }
  | { type: "suggestion"; data: Suggestion }
  | { type: "suggestion_update"; data: Suggestion }
  | { type: "status"; data: { status: string } }
  | { type: "summary"; data: Summary }
  | { type: "crm_sync"; data: { synced: boolean } }
  | { type: "error"; data: { message: string } };
