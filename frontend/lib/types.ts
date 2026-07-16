export interface Meeting {
  id: string;
  title: string;
  platform: string;
  customer_company: string;
  customer_contact: string;
  rep_name: string;
  status: "scheduled" | "live" | "ended";
  crm_company_id: string | null;
  recall_bot_id?: string | null;
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

export interface Envelope {
  assumptions?: string[];
  risks?: string[];
  next_actions?: string[];
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
  grounded?: boolean;
  access_scope?: string;
  envelope?: Envelope;
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
  health?: "healthy" | "limited" | "expired" | "error" | "demo" | "disconnected";
  health_reason?: string;
  can_test?: boolean;
  custom?: boolean;
  transport?: string;
}

export interface ConnectorCheck {
  ok: boolean;
  status: string;
  health: string;
  reason: string;
}

export interface MeetingHealth {
  status: "good" | "fair" | "poor";
  turns: number;
  grounded: number;
  grounded_pct: number;
  scopes: Record<string, number>;
  scope_pct: Record<string, number>;
  deep_turns: number;
  deep_pct: number;
  abstained: number;
  avg_latency_ms: number;
  avg_deep_latency_ms: number;
  connectors: {
    connected: number;
    healthy: number;
    broken: { name: string; health: string; reason: string }[];
  };
  recommendations: string[];
}

export interface CalendarEvent {
  id: string;
  title: string;
  start: string;
  end: string;
  all_day: boolean;
  attendees: string[];
  organizer: string;
  meeting_url: string;
  html_link: string;
}

export interface UpcomingMeetings {
  connected: boolean;
  events: CalendarEvent[];
  error: string | null;
  detail?: string;
  days?: number;
}

export interface MeetingPrep {
  event_id: string;
  title: string;
  customer: string;
  markdown: string;
  sources: { label: string; type: string; detail: string; url: string }[];
  engine: string;
  generated_at: string | null;
  cached: boolean;
}
// The prep endpoint returns a finished brief, a fast PARTIAL brief that's still being refined
// (markdown present + generating:true + partial:true → show it and keep polling), a bare
// {generating:true} (nothing yet — poll again), or {error}.
export interface MeetingPrepResponse extends Partial<MeetingPrep> {
  generating?: boolean;
  partial?: boolean;
  error?: string;
}

export interface MeetingPrepRecord {
  found: boolean;
  title?: string;
  customer?: string;
  markdown?: string;
  sources?: { label: string; type: string; detail: string; url: string }[];
  engine?: string;
  generated_at?: string | null;
}

export interface ScoreDimension {
  name: string;
  score: number;
  comment: string;
}
export interface CoachingTip {
  tip: string;
  example: string;
}
export interface Scorecard {
  status?: string;
  detail?: string;
  rep_name: string;
  overall_score: number;
  headline: string;
  dimensions: ScoreDimension[];
  strengths: string[];
  improvements: string[];
  coaching_tips: CoachingTip[];
  metrics: Record<string, number>;
}
export interface TeamRep {
  rep_name: string;
  calls: number;
  avg_score: number;
  dimensions: { name: string; score: number }[];
  top_improvements: string[];
  recent: { date: string; score: number }[];
  trend: number;
}
export interface TeamCoaching {
  scored_calls: number;
  reps: TeamRep[];
}

export interface TeamMemberMeeting {
  id: string;
  title: string;
  customer: string;
  date: string;
  status: string;
  persona: "sales" | "tech";
  suggestions: number;
  actions: number;
  actions_done: number;
  has_transcript: boolean;
  has_summary: boolean;
  has_recording: boolean;
  score: number | null;
}
export interface TeamMemberAction {
  id: string;
  kind: string;
  icon: string;
  title: string;
  status: "proposed" | "executed" | "failed" | "rejected" | "undone";
  url: string;
  result_status: string;
  meeting_id: string;
  meeting_title: string;
  when: string;
}
export interface TeamMemberActivity {
  total: number;
  executed: number;
  failed: number;
  undone: number;
  proposed: number;
}
export interface TeamMember {
  id: string;
  name: string;
  email: string;
  role: string;
  team: string;
  meeting_count: number;
  avg_score: number | null;
  activity?: TeamMemberActivity;
  recent_actions?: TeamMemberAction[];
  meetings: TeamMemberMeeting[];
}
export interface TeamMembers {
  members: TeamMember[];
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
  grounded_pct: number;
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
  status: "proposed" | "executed" | "rejected" | "failed" | "undone";
  approver: string | null;
  result: Record<string, unknown>;
  error: string | null;
  undoable?: boolean;
  created_at: string;
  decided_at: string | null;
}

export interface ActionHistoryItem {
  id: string;
  meeting_id: string;
  meeting_title: string;
  kind: string;
  title: string;
  status: "executed" | "failed" | "undone";
  result_status: string;
  url: string;
  error: string | null;
  undoable: boolean;
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

export interface OrgMember {
  id: string;
  email: string;
  name: string;
  role: string;
  team: string;
  manager_id: string | null;
  manager_name: string | null;
}
export interface OrgInfo {
  id: string;
  name: string;
  plan: string;
  your_role: string;
  can_manage: boolean;
  members: OrgMember[];
}

// Advisory context — the employee's personal profile (injected into every AI request).
export interface UserProfile {
  designation?: string;
  manager_name?: string;
  location?: string;
  timezone?: string;
  focus?: string;
  responsibilities?: string[];
  decision_authority?: string[];
  working_style?: string[];
  preferred_output?: string[];
}
export interface MeInfo {
  id: string;
  email: string;
  name: string;
  org_id: string | null;
  role?: string;
  autopilot?: boolean;
  team?: string;
  language?: string;
  profile?: UserProfile;
  custom_context?: string;
  capabilities?: Record<string, boolean>;
  capability_catalog?: { key: string; label: string; description: string; default: boolean }[];
}
export interface CompanyProfile {
  industry?: string;
  locations?: string[];
  products?: string[];
  tech_stack?: string[];
  priorities?: string[];
}
export interface OrgProfile {
  name: string;
  description: string;
  profile: CompanyProfile;
  can_manage: boolean;
}

export interface Insight {
  type: string;      // decision_without_owner | unassigned_action | open_question | risk | contradiction | deadline | missing_stakeholder | follow_up
  severity: "info" | "warn" | "high";
  text: string;
}

export interface ShareLink {
  token: string;
  url: string;
  scopes: string[];
  expires_at: string | null;
  revoked: boolean;
  view_count: number;
  created_at: string | null;
}
export interface ShareBundle {
  meeting: { title: string; customer_company: string; date: string | null; status: string };
  scopes: string[];
  summary?: {
    executive_summary: string;
    key_decisions: string[];
    risks: string[];
    action_items: string[];
    customer_concerns: string[];
    follow_up_email: string;
  } | null;
  prep?: { title: string; markdown: string; sources: Source[] } | null;
  transcript?: { speaker: string; role: string; text: string }[];
  recording?: { status: string; url: string | null; detail?: string };
}

export type WSEvent =
  | { type: "transcript"; data: Segment }
  | { type: "intent"; data: { intent_type: string; family: string; confidence: number; query_text: string; actionable: boolean } }
  | { type: "suggestion"; data: Suggestion }
  | { type: "suggestion_update"; data: Suggestion }
  | { type: "status"; data: { status: string } }
  | { type: "summary"; data: Summary }
  | { type: "crm_sync"; data: { synced: boolean } }
  | { type: "insights"; data: Insight[] }
  | { type: "error"; data: { message: string } };

export interface AskResult {
  answer: string;
  evidence: string[];
  sources: { label: string; type: string; detail: string; url: string }[];
  confidence: number;
  engine: string;
  grounded: boolean;
  access_scope?: string; // user | web | demo | none
  assumptions?: string[];
  risks?: string[];
  next_actions?: string[];
  persona: "sales" | "tech";
  intent: string;
  connected: string[]; // sources available to the agent
  used: string[]; // sources it actually cited
  deep_ran: boolean;
  latency_ms: number;
  thread_id?: string;
  thread_title?: string | null;
}

export interface AskThreadSummary {
  id: string;
  title: string;
  updated_at: string;
}

export interface AskStage {
  stage: string;
  label: string;
  sources?: string[];
}

export interface AskThreadMessage {
  role: "user" | "assistant";
  content: string;
  meta?: AskResult;
  created_at?: string;
}

export interface AskThreadDetail {
  id: string;
  title: string;
  messages: AskThreadMessage[];
}

export interface CostReport {
  days: number;
  totals: {
    calls: number;
    cost_usd: number;
    input_tokens: number;
    output_tokens: number;
    cache_read_tokens: number;
    cache_write_tokens: number;
  };
  by_model: { model: string; cost_usd: number; calls: number }[];
  by_call_type: { call_type: string; cost_usd: number; calls: number }[];
  by_user: { user_id: string; name?: string; cost_usd: number; calls: number }[];
  top_meetings: { meeting_id: string; title?: string; cost_usd: number; calls: number }[];
  by_day: { date: string; cost_usd: number; calls: number }[];
}
