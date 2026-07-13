import type { Meeting, Segment, Suggestion, Summary, Metrics, Connector, ConnectorCheck, MeetingHealth, ProposedAction, ActionHistoryItem, BillingInfo, OrgInfo, UpcomingMeetings, MeetingPrep, MeetingPrepResponse, MeetingPrepRecord, Scorecard, TeamCoaching, TeamMembers, AskResult, AskStage, AskThreadSummary, AskThreadDetail, MeInfo, UserProfile, CompanyProfile, OrgProfile, Insight, ShareLink, ShareBundle } from "./types";

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
  setCapabilities: (capabilities: Record<string, boolean>) =>
    request<{ capabilities: Record<string, boolean> }>("/api/me/capabilities", {
      method: "POST",
      body: JSON.stringify({ capabilities }),
    }),
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
  listMeetings: (params?: { limit?: number; offset?: number; q?: string; status?: string; days?: number }) => {
    const qs = new URLSearchParams();
    if (params?.limit != null) qs.set("limit", String(params.limit));
    if (params?.offset != null) qs.set("offset", String(params.offset));
    if (params?.q) qs.set("q", params.q);
    if (params?.status) qs.set("status", params.status);
    if (params?.days) qs.set("days", String(params.days));
    const s = qs.toString();
    return request<{ items: Meeting[]; total: number }>(`/api/meetings${s ? `?${s}` : ""}`);
  },
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
  // Guaranteed one-click download: streams through the backend with Content-Disposition: attachment.
  // A plain <a> can't send the Bearer header, so the session token rides as a query param.
  recordingDownloadUrl: async (id: string): Promise<string> => {
    const token = await authToken();
    return `${API}/api/meetings/${id}/recording/download${token ? `?token=${encodeURIComponent(token)}` : ""}`;
  },
  scorecard: (id: string, refresh = false, peek = false) => {
    const q = refresh ? "?refresh=1" : peek ? "?peek=1" : "";
    return request<Scorecard>(`/api/meetings/${id}/scorecard${q}`);
  },
  meetingHealth: (id: string) => request<MeetingHealth>(`/api/meetings/${id}/health`),
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
  undoAction: (actionId: string) => request<ProposedAction>(`/api/actions/${actionId}/undo`, { method: "POST" }),
  actionHistory: () => request<{ items: ActionHistoryItem[] }>("/api/me/action-history"),
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
  upcomingMeetings: (days?: number) =>
    request<UpcomingMeetings>(`/api/calendar/upcoming${days ? `?days=${days}` : ""}`),
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
  checkConnector: (provider: string) =>
    request<ConnectorCheck>(`/api/connectors/${provider}/check`, { method: "POST" }),
  addCustomMcp: (body: { name: string; mcp_url: string; token?: string; transport?: string; category?: string; icon?: string }) =>
    request<{ ok: boolean; provider: string; status: string; has_mcp: boolean }>(`/api/connectors/custom`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  suggestionFeedback: (suggestionId: string, body: { rating?: string; correction?: string }) =>
    request<{ ok: boolean; rating: string; correction: string }>(`/api/suggestions/${suggestionId}/feedback`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  ask: (query: string, context = "", meeting_id?: string, selection?: string[], thread_id?: string | null) =>
    request<AskResult>("/api/ask", { method: "POST", body: JSON.stringify({ query, context, meeting_id, selection, thread_id }) }),

  // Streaming Ask (SSE over fetch — EventSource can't POST a body). Emits real per-stage
  // progress, then the final answer. Handlers are called as events arrive.
  askStream: async (
    body: { query: string; context?: string; meeting_id?: string; selection?: string[]; thread_id?: string | null },
    handlers: { onStage?: (s: AskStage) => void; onAnswer?: (a: AskResult) => void; onError?: (msg: string) => void }
  ): Promise<void> => {
    const token = await authToken();
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const res = await fetch(`${API}/api/ask/stream`, { method: "POST", headers, body: JSON.stringify(body) });
    if (!res.ok || !res.body) {
      handlers.onError?.(`${res.status} ${res.statusText}`);
      return;
    }
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let idx: number;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        let event = "message";
        let data = "";
        for (const line of chunk.split("\n")) {
          if (line.startsWith("event:")) event = line.slice(6).trim();
          else if (line.startsWith("data:")) data += line.slice(5).trim();
        }
        if (!data) continue;
        let parsed: unknown;
        try { parsed = JSON.parse(data); } catch { continue; }
        if (event === "stage") handlers.onStage?.(parsed as AskStage);
        else if (event === "answer") handlers.onAnswer?.(parsed as AskResult);
        else if (event === "error") handlers.onError?.((parsed as { message?: string }).message || "error");
      }
    }
  },

  // Ask conversation threads (history)
  askThreads: () => request<{ threads: AskThreadSummary[] }>("/api/ask/threads"),
  createAskThread: (title?: string) =>
    request<AskThreadSummary>("/api/ask/threads", { method: "POST", body: JSON.stringify({ title: title || null }) }),
  getAskThread: (id: string) => request<AskThreadDetail>(`/api/ask/threads/${id}`),
  renameAskThread: (id: string, title: string) =>
    request<AskThreadSummary>(`/api/ask/threads/${id}`, { method: "PATCH", body: JSON.stringify({ title }) }),
  deleteAskThread: (id: string) => request<{ ok: boolean }>(`/api/ask/threads/${id}`, { method: "DELETE" }),

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
