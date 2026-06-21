# Connectors, Auth & the Agent (v0.2)

This is the multi-tenant layer: real Claude, per-employee SSO, and per-user OAuth
connectors fetched live over MCP — each employee only ever sees their own data.

## How permission-scoped access works

```
Employee ──Clerk SSO──▶ App ──"Connect HubSpot"──▶ provider OAuth consent
                                                          │
                                  encrypted token stored per (user, provider)
                                                          │
  Customer asks a question ──▶ Claude (agentic loop) ──mcp_servers[]──▶ provider MCP
                                                          │   (Bearer = THIS user's token)
                                              provider enforces the user's own permissions
```

There is **no shared service account**. Every fetch runs as the employee, so the
source system decides what's visible. We never widen access; disconnect wipes tokens.

## 1. Claude (the agent runtime)

```bash
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-sonnet-4-6        # fast enough for the live <5s path
AGENT_ENGINE=auto                        # → messages_mcp when a key is present
```

Two interchangeable Claude engines (`AGENT_ENGINE`):

- **`agent_sdk`** — `agent/claude_sdk.py` runs the **Claude Agent SDK** through the
  authenticated `claude` CLI (no API key) with an **in-process MCP server** whose tools
  expose the data layer. Claude genuinely calls the MCP tools. Best for local dev / when
  you're signed into Claude Code; tools can also point at remote provider MCP. *(Verified
  live — a customer question triggers real CRM + document tool calls; ~13–15s/turn.)*
- **`messages_mcp`** — `agent/claude_agent.py` runs Claude's tool-use loop via the
  Anthropic **MCP connector** (`messages.create(mcp_servers=[...])`), subprocess-free and
  horizontally scalable. Best for production with an API key + hosted remote MCP.

With neither configured, the deterministic offline composer is used (the app always runs).
Latency note: the full agent loop runs ~10–15s/turn; the live `<5s` SLA is met by the
two-tier design (fast deterministic router for the hot path, agent loop for depth).

## 2. Auth (Clerk)

```bash
# Backend (.env)
CLERK_SECRET_KEY=sk_...
CLERK_PUBLISHABLE_KEY=pk_...
CLERK_ISSUER=https://<your-app>.clerk.accounts.dev
TOKEN_ENCRYPTION_KEY=<a long random secret>     # REQUIRED in prod (Fernet key vault)

# Frontend (.env.local)
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_...
```

- Unset → **DEV mode**: a single seeded `dev_user`, no login, mock data.
- Set → the frontend mounts `<ClerkProvider>` and gates the app; the backend verifies
  the session JWT against Clerk's JWKS (`security/auth.py`) and upserts the `User`.
- The frontend attaches the Clerk token to every API call and the meeting WebSocket;
  the WS also checks meeting ownership.

## 3. Connectors (user-owned — the Anthropic key is the *only* platform secret)

**Every connector is connected by the user themselves; the admin configures nothing.**
On the Connections page each user clicks **Connect** and supplies *their own* access
token/key plus an MCP server URL (prefilled with the provider's hosted MCP where one
exists). The token is stored encrypted under that user, and the agent calls the provider
**as that user** — so access is scoped to exactly what they can see.
(`POST /api/connectors/{provider}/connect-token`.)

### Optional: admin OAuth (convenience only)

If you'd rather offer a one-click OAuth flow for a provider, register an OAuth app and set
its client id/secret — an extra **OAuth** button then appears on that card. This is purely
optional; the BYO-token path always works without it. Redirect URI:

```
{APP_BASE_URL}/api/connectors/{provider}/callback
```

| Provider | Env | MCP server |
|---|---|---|
| HubSpot | `HUBSPOT_CLIENT_ID` / `HUBSPOT_CLIENT_SECRET` | hosted (`HUBSPOT_MCP_URL`, default set) |
| Notion | `NOTION_CLIENT_ID` / `NOTION_CLIENT_SECRET` | hosted (`NOTION_MCP_URL`, default set) |
| Google Drive | `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | self-hosted (`GOOGLE_DRIVE_MCP_URL`) |
| Gmail | `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | self-hosted (`GMAIL_MCP_URL`) |

Add more connectors by appending to `connectors/registry.py` — Slack, Jira,
Salesforce, etc. all follow the same OAuth + MCP shape. A connector with no MCP URL
still stores the user's token (ready for a direct-API adapter).

Flow (`connectors/manager.py`):
1. Employee clicks **Connect** → `GET /api/connectors/{p}/connect` returns a signed-state
   authorize URL → browser redirects to the provider.
2. Provider redirects to the callback → code exchanged for tokens → **encrypted** and stored.
3. During meetings, `active_mcp_servers(user)` decrypts the token, refreshes if expiring,
   and hands Claude the user's live MCP servers.

## 4. Real meeting capture (Recall.ai)

```bash
RECALL_API_KEY=...
RECALL_REGION=us-east-1
```

With a key, the dashboard's **"Bring the copilot to a real call"** sends a bot into a real
Google Meet / Zoom / Teams call: `POST /api/meetings/live {meeting_url}` dispatches a
Recall bot ([`integrations/recall.py`](../backend/app/integrations/recall.py)) that streams
live transcript to `POST /api/webhooks/recall`, which feeds the **same** `process_utterance`
pipeline the simulator uses — so the copilot behaves identically on real calls. The webhook
maps the host/rep vs. customer, and customer turns trigger the agent. Without a key, the
built-in simulator remains the capture source. (Recall's cloud must reach your webhook, so
in local dev expose `APP_BASE_URL` via a tunnel.)

## What's real vs. needs your setup

- **Real & tested:** **live Claude + MCP run** (Agent SDK + in-process MCP, end-to-end in
  the UI with the "Claude · live" badge), the Anthropic MCP-connector agent, the Recall.ai
  bot + transcript-webhook wiring, encrypted token vault, OAuth authorize/exchange/refresh,
  per-user MCP exposure + isolation, Clerk JWT verification, the connections UI,
  ownership-checked WebSocket.
- **Needs you (only you can):** create the OAuth apps + Clerk instance + Recall.ai key and
  provide them; point Google Drive/Gmail at a self-hosted MCP (no official hosted one yet);
  expose your webhook URL for Recall in local dev.

Until then the app runs in DEV mode with seeded data and offline answers — same UX,
no credentials required.
