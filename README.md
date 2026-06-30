# AI Sales Meeting Copilot

A real-time AI "virtual Sales Engineer" that attends sales meetings, understands the
conversation as it happens, detects customer intent, retrieves answers from your CRM and
enterprise knowledge, suggests grounded responses with sources + confidence, recommends
next actions, and automates the post-meeting CRM updates.

Built to the **AI Sales Meeting Copilot Platform PRD** (MVP scope, FR-001 → FR-007).

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Google Meet (simulated)  ──live transcript──▶  WebSocket  ──▶  Copilot UI │
│                                                     │                       │
│                                                     ▼                       │
│                                        LangGraph-style Agent Pipeline       │
│                          intent ─▶ retrieve ─▶ answer ─▶ recommend actions  │
│                                       │            │                        │
│                          ┌────────────┴───┐   ┌────┴──────────┐            │
│                          │ CRM (HubSpot)  │   │ Enterprise     │            │
│                          │ deals/tickets  │   │ Search (Drive) │            │
│                          └────────────────┘   │ + Vector store │            │
│                                                └────────────────┘           │
│  End meeting ─▶ Summary (decisions/risks/actions) ─▶ CRM notes/tasks/email  │
└──────────────────────────────────────────────────────────────────────────┘
```

## What this implements (MVP scope)

| PRD requirement | Status |
|---|---|
| FR-001 Meeting attendance (Google Meet) | ✅ via live meeting **simulator** (real-bot interface ready) |
| FR-002 Live transcript (<2s) | ✅ streamed over WebSocket |
| FR-003 Real-time intent detection | ✅ pricing / contract / support / product / security / renewal + more |
| FR-004 Enterprise retrieval (HubSpot + Drive, <3s) | ✅ CRM + vector/lexical knowledge retrieval |
| FR-005 Suggested responses (Answer · Source · Confidence) | ✅ grounded, cited, scored |
| FR-006 Action recommendations | ✅ intent-driven next-best-actions |
| FR-007 Post-meeting automation (summary · CRM notes · follow-up email) | ✅ auto-generated, one-click CRM sync |
| Security: SSO / RBAC / audit / PII redaction | ✅ Google sign-in, per-user data isolation, encrypted token vault, audit log |
| **Multi-tenant connectors** (per-employee OAuth) | ✅ HubSpot · Google Drive · Gmail · Notion via remote MCP + OAuth 2.1 |
| **Live, permission-scoped retrieval** | ✅ Claude agentic loop over each employee's own MCP tools — sees only what they can |

## Architecture (per PRD)

| Layer | PRD spec | This build |
|---|---|---|
| Frontend | Next.js + TypeScript | ✅ Next.js 15 App Router |
| Backend | FastAPI | ✅ FastAPI + WebSockets |
| Agent framework | LangGraph | ✅ LangGraph-compatible `StateGraph` pipeline (drop-in for `langgraph`) |
| Realtime | WebSockets + Redis Streams | ✅ WebSockets (Redis pub/sub optional) |
| Vector DB | Qdrant | ✅ pluggable: local cosine store by default, Qdrant via env |
| Storage | PostgreSQL | ✅ SQLAlchemy: SQLite by default, Postgres via `DATABASE_URL` |
| Agent runtime | LangGraph | ✅ **Claude** agentic loop via Anthropic's native MCP connector |
| Connectors | (Phase 2) | ✅ per-employee OAuth → **remote MCP** (HubSpot/Drive/Gmail/Notion) |
| Auth | SSO / RBAC | ✅ **Google sign-in** + per-user token vault (Fernet); DEV-mode fallback |
| Observability | OpenTelemetry / Prometheus | ⚙️ structured logging + `/metrics` latency counters |

**Runs with zero credentials** (DEV mode: single user, seeded data, offline answers).
Add keys to light up real Claude + per-employee connectors — see
[`docs/CONNECTORS_AND_AUTH.md`](docs/CONNECTORS_AND_AUTH.md).

## Quick start

> 📖 **One complete setup guide — prerequisites, every env var, and step-by-step for each
> connector/integration: [SETUP.md](SETUP.md).**


```bash
# 1. Backend  (terminal 1)
cd backend
./run.sh                     # creates venv, installs deps, seeds demo data, serves :8000

# 2. Frontend (terminal 2)
cd frontend
npm install && npm run dev   # serves :3000
```

Open http://localhost:3000 → **Start demo meeting** → watch the copilot work live.

See [`backend/README.md`](backend/README.md) and [`frontend/README.md`](frontend/README.md) for details,
and [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the deep dive.
