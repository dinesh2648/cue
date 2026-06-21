import type { Meeting, Segment, Suggestion, Summary, Metrics, Connector } from "./types";

export const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
export const WS_BASE = API.replace(/^http/, "ws");

// Auth token bridge — Clerk sets this in real mode; null in dev mode.
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
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export const api = {
  authConfig: () =>
    request<{ dev_mode: boolean; clerk_publishable_key: string | null; agent_engine: string; llm_provider: string; recall_enabled: boolean }>(
      "/api/auth/config"
    ),
  me: () => request<{ id: string; email: string; name: string; org_id: string | null }>("/api/me"),

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
  metrics: () => request<Metrics>("/metrics"),
  health: () =>
    request<{ status: string; llm_provider: string; agent_engine: string; knowledge_backend: string; dev_mode: boolean }>(
      "/health"
    ),

  // Connectors
  connectors: () => request<Connector[]>("/api/connectors"),
  connectUrl: (provider: string) => request<{ authorize_url: string }>(`/api/connectors/${provider}/connect`),
  connectToken: (provider: string, token: string, mcp_url?: string, account_label?: string) =>
    request<{ ok: boolean; status: string; has_mcp: boolean }>(`/api/connectors/${provider}/connect-token`, {
      method: "POST",
      body: JSON.stringify({ token, mcp_url: mcp_url || null, account_label: account_label || "" }),
    }),
  disconnect: (provider: string) => request<{ ok: boolean }>(`/api/connectors/${provider}/disconnect`, { method: "POST" }),
};

export async function meetingSocket(id: string): Promise<WebSocket> {
  const token = await authToken();
  const q = token ? `?token=${encodeURIComponent(token)}` : "";
  return new WebSocket(`${WS_BASE}/ws/meetings/${id}${q}`);
}
