import type { Meeting, Segment, Suggestion, Summary, Metrics, Connector, ProposedAction, BillingInfo, OrgInfo, UpcomingMeetings, MeetingPrep, MeetingPrepResponse, MeetingPrepRecord, Scorecard, TeamCoaching, TeamMembers, AskResult, MeInfo, UserProfile, CompanyProfile, OrgProfile, Insight, ShareLink, ShareBundle } from "./types";

export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

export const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
export const WS_BASE = API.replace(/^http/, "ws");

// Auth token bridge — the AuthProvider sets this to read the session token
// (issued after Google sign-in) from localStorage; null in dev mode.
type TokenGetter = () => Promise<string | null>;
let _tokenGetter: TokenGetter | null = null;
export function setTokenGetter(fn: TokenGetter | null) {
  _tokenGetter = fn;
}
export async function authToken(): Promise<string | null> {
  try {
    return _tokenGetter ? await _tokenGetter() : null;
  } catch {
    return null;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await authToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((init.headers as Record<string, string>) || {}),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${API}${path}`, { ...init, headers });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* non-JSON error */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  authConfig: () =>
    request<{ dev_mode: boolean; auth_mode: string; google_login_url: string | null; agent_engine: string; llm_provider: string; recall_enabled: boolean }>(
      "/api/auth/config"
    ),
  me: () => request<MeInfo>("/api/me"),
  setAutopilot: (enabled: boolean) =>
    request<{ autopilot: boolean }>("/api/me/autopilot", { method: "POST", body: JSON.stringify({ enabled }) }),
  setProfile: (patch: Partial<UserProfile> & { team?: string; language?: string; custom_context?: string }) =>
    request<{ team: string; profile: UserProfile; custom_context: string }>("/api/me/profile", {
      method: "POST",
      body: JSON.stringify(patch),
    }),
  orgProfile: () => request<OrgProfile>("/api/org/profile"),
  setOrgProfile: (patch: Partial<CompanyProfile> & { name?: string; description?: string }) =>
    request<{ name: string; description: string; profile: CompanyProfile }>("/api/org/profile", {
      method: "POST",
      body: JSON.stringify(patch),
    }),

  createDemo: () => request<Meeting>("/api/meetings/demo", { method: "POST" }),
  joinLive: (meeting_url: string, fields: Partial<{ title: string; customer_company: string; customer_contact: string }> = {}) =>
    request<Meeting>("/api/meetings/live", { method: "POST", body: JSON.stringify({ meeting_url, ...fields }) }),
  listMeetings: () => request<Meeting[]>("/api/meetings"),
  getMeeting: (id: string) => request<Meeting>(`/api/meetings/${id}`),
  start: (id: string, scenario?: string) =>
    request<{ started: boolean; already_running: boolean }>(`/api/meetings/${id}/start`, {
      method: "POST",
      body: JSON.stringify({ scenario: scenario ?? null }),
    }),
  transcript: (id: string) => request<Segment[]>(`/api/meetings/${id}/transcript`),
  suggestions: (id: string) => request<Suggestion[]>(`/api/meetings/${id}/suggestions`),
  end: (id: string) => request<Summary>(`/api/meetings/${id}/end`, { method: "POST" }),
  summary: (id: string) => request<Summary>(`/api/meetings/${id}/summary`),
  recording: (id: string) => request<{ status: string; url: string | null }>(`/api/meetings/${id}/recording`),
  scorecard: (id: string, refresh = false) =>
    request<Scorecard>(`/api/meetings/${id}/scorecard${refresh ? "?refresh=1" : ""}`),
  meetingInsights: (id: string) =>
    request<{ insights: Insight[]; running_summary: string; current_topic: string; open_questions: string[]; decisions: string[]; action_items: string[]; risks: string[] }>(
      `/api/meetings/${id}/insights`
    ),
  teamCoaching: () => request<TeamCoaching>("/api/team/coaching"),
  teamMembers: () => request<TeamMembers>("/api/team/members"),

  // Approve-then-act
  listActions: (id: string) => request<ProposedAction[]>(`/api/meetings/${id}/actions`),
  proposeAction: (id: string, action: Record<string, unknown>) =>
    request<ProposedAction>(`/api/meetings/${id}/actions/propose`, { method: "POST", body: JSON.stringify({ action }) }),
  approveAction: (actionId: string, payload?: Record<string, unknown>) =>
    request<ProposedAction>(`/api/actions/${actionId}/approve`, {
      method: "POST",
      body: JSON.stringify({ payload: payload || null }),
    }),
  rejectAction: (actionId: string) => request<ProposedAction>(`/api/actions/${actionId}/reject`, { method: "POST" }),
  approveAll: (id: string) => request<ProposedAction[]>(`/api/meetings/${id}/actions/approve-all`, { method: "POST" }),
  jiraProjects: () => request<{ key: string; name: string }[]>("/api/jira/projects"),
  metrics: () => request<Metrics>("/metrics"),
  health: () =>
    request<{ status: string; llm_provider: string; agent_engine: string; knowledge_backend: string; dev_mode: boolean }>(
      "/health"
    ),

  // Billing / org (SaaS)
  billing: () => request<BillingInfo>("/api/billing"),
  checkout: (plan: string) =>
    request<{ url: string; live: boolean }>("/api/billing/checkout", { method: "POST", body: JSON.stringify({ plan }) }),
  portal: () => request<{ url: string }>("/api/billing/portal", { method: "POST" }),
  org: () => request<OrgInfo>("/api/org"),
  updateMember: (memberId: string, patch: { role?: string; team?: string; manager_id?: string | null }) =>
    request<{ id: string; role: string; team: string; manager_id: string | null }>(
      `/api/org/members/${memberId}`,
      { method: "POST", body: JSON.stringify(patch) }
    ),

  // Calendar (upcoming meetings from the user's connected Google Calendar)
  upcomingMeetings: () => request<UpcomingMeetings>("/api/calendar/upcoming"),
  // Pre-meeting prep brief (researched across connected sources + prior notes; cached)
  meetingPrep: (eventId: string, refresh = false) =>
    request<MeetingPrepResponse>(`/api/calendar/prep/${encodeURIComponent(eventId)}${refresh ? "?refresh=1" : ""}`),
  // Prep brief tied to a meeting record (read-only; what was prepared before this meeting)
  meetingPrepRecord: (meetingId: string) =>
    request<MeetingPrepRecord>(`/api/meetings/${meetingId}/prep`),

  // Connectors
  connectors: () => request<Connector[]>("/api/connectors"),
  connectUrl: (provider: string) => request<{ authorize_url: string; mode: string }>(`/api/connectors/${provider}/connect`),
  connectToken: (provider: string, token: string, mcp_url?: string, account_label?: string) =>
    request<{ ok: boolean; status: string; has_mcp: boolean }>(`/api/connectors/${provider}/connect-token`, {
      method: "POST",
      body: JSON.stringify({ token, mcp_url: mcp_url || null, account_label: account_label || "" }),
    }),
  disconnect: (provider: string) => request<{ ok: boolean }>(`/api/connectors/${provider}/disconnect`, { method: "POST" }),

  ask: (query: string, context = "", meeting_id?: string, selection?: string[]) =>
    request<AskResult>("/api/ask", { method: "POST", body: JSON.stringify({ query, context, meeting_id, selection }) }),

  // Public shareable links for meeting artifacts
  createShare: (meetingId: string, scopes: string[], expires_days: number | null) =>
    request<ShareLink>(`/api/meetings/${meetingId}/share`, { method: "POST", body: JSON.stringify({ scopes, expires_days }) }),
  listShares: (meetingId: string) => request<ShareLink[]>(`/api/meetings/${meetingId}/shares`),
  revokeShare: (token: string) => request<{ revoked: boolean }>(`/api/share/${token}/revoke`, { method: "POST" }),
  publicShare: (token: string) => request<ShareBundle>(`/api/share/${token}`),
};

export async function meetingSocket(id: string): Promise<WebSocket> {
  const token = await authToken();
  const q = token ? `?token=${encodeURIComponent(token)}` : "";
  return new WebSocket(`${WS_BASE}/ws/meetings/${id}${q}`);
}
