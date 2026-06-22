# AI Sales Meeting Copilot — Delivery & Handoff

A production-architected, runnable **AI "virtual Sales Engineer"** that joins customer
meetings, understands the conversation live, answers questions from the rep's own CRM +
enterprise tools (with sources and confidence), and automates the post-meeting CRM updates.

Built to the *AI Sales Meeting Copilot Platform PRD*. **Runs out of the box with zero
credentials** (demo mode); activates real Claude + per-user connectors via configuration.

---

## What's delivered

```
AISalesAgent/
├── backend/      FastAPI · agent pipeline · connectors · realtime · tests
├── frontend/     Next.js 15 + TypeScript · live console · connections UI
├── docs/         ARCHITECTURE.md · CONNECTORS_AND_AUTH.md
├── docker-compose.yml   optional Postgres/Qdrant/Redis (production stack)
└── README.md
```

## Run it (two terminals)

```bash
cd backend  && ./run.sh        # http://localhost:8000  (venv, deps, seed, serve)
cd frontend && npm install && npm run dev   # http://localhost:3000
```

Open **http://localhost:3000 → Start demo meeting**. Watch the copilot work a live
(simulated) Northwind Trading expansion call end to end.

## Launch (production)

```bash
# Backend
cd backend && python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
#   set production env in backend/.env (DATABASE_URL=postgres…, ANTHROPIC_API_KEY,
#   CLERK_*, TOKEN_ENCRYPTION_KEY, provider *_CLIENT_ID/SECRET, RECALL_API_KEY)
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Frontend (build once, serve)
cd frontend && npm ci && npm run build && npm start    # or deploy to Vercel
#   set NEXT_PUBLIC_API_URL and NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY

# Optional managed services (PRD stack)
docker compose up -d        # Postgres + Qdrant + Redis
```

Verified launch-ready: production build passes (5 routes), **38/38 end-to-end checks** and
**8/8 unit tests** green, runs with zero credentials and scales up via env.

## Capabilities (all verified end-to-end)

| Capability | Status |
|---|---|
| Live meeting transcript (Google Meet sim + **Recall.ai** for real Meet/Zoom/Teams) | ✅ |
| Real-time intent detection (contract / security / support / pricing / renewal / product) | ✅ |
| Grounded answers — **Answer · Sources · Confidence** | ✅ |
| Next-best-action recommendations | ✅ |
| Post-meeting summary (decisions · risks · action items · concerns) | ✅ |
| Auto CRM write-back (recap note · tasks · follow-up email draft) | ✅ |
| **Two-tier latency**: instant answer (<5s SLA) → Claude+MCP deep upgrade in place | ✅ |
| **Per-user connectors** (each employee BYO): HubSpot · Drive · Gmail · Calendar · Notion · LinkedIn | ✅ |
| **SSO** (Clerk) · per-user data isolation · encrypted token vault · audit log | ✅ |

## Architecture (per PRD)

Next.js/TS · FastAPI · **Claude Agent SDK** (in-process MCP) **+** Anthropic MCP-connector ·
WebSockets · vector/TF-IDF retrieval · SQLAlchemy (SQLite→Postgres) · OpenAI embeddings
(optional) · Docker/K8s-ready. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## The security model (important for buyers)

**The only platform secret is the Anthropic API key.** Every data connector is connected
by the *individual employee* with their *own* token — stored encrypted, used only on their
behalf — so the copilot can only ever read what that person can already access. No shared
service accounts. Access scoping is enforced by the source systems themselves.

## What's live now vs. what needs your keys

- **Live with zero setup:** the full demo (simulated meeting, seeded CRM + docs, instant
  grounded answers, summary, CRM write-back) and a real local **Claude + MCP** run if you're
  signed into Claude Code.
- **Switch on with config** ([docs/CONNECTORS_AND_AUTH.md](docs/CONNECTORS_AND_AUTH.md)):
  `ANTHROPIC_API_KEY` (cloud Claude), Clerk (multi-user SSO), `RECALL_API_KEY` (real meeting
  bots), and each employee connecting their own tools on the **Connections** page.

## Verification summary

- Backend: **8/8 tests pass**; full meeting lifecycle (start → 6 intents → end → summary →
  CRM write-back) verified; idempotent `/end`.
- Frontend: production build clean; live console + connections UI verified in-browser.
- Live Claude+MCP and the two-tier instant→deep upgrade verified in the UI.

## Sales assets

- **Client one-pager** (shareable web page): https://claude.ai/code/artifact/bd44fe24-90a0-402a-8f46-c037aee1cb19
  — polished product overview to send to a prospect (problem → solution → security → outcomes).
- **Demo script**: [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) — a 5-minute live walkthrough with
  talking points, the "wow" moments, and objection handling. Runs with zero credentials.

## Suggested commercial positioning

- **Per-seat SaaS** for sales orgs; value = faster, accurate answers in-meeting + automatic
  CRM hygiene (the PRD's 30% time-saved / 80% CRM-automation targets).
- Differentiators: **permission-correct** (per-user access), **grounded + cited** answers,
  **bring-your-own connectors**, and a **two-tier** design that's both instant and deep.

## Roadmap (next increments)

Near-term (Sales): real per-user CRM write-back via the employee's HubSpot MCP ·
MCP-native OAuth (zero token-pasting) · battlecards / renewal-risk / buying-signal detection.

**Strategic — multi-vertical platform:** Sales is the pilot; the substrate is designed to
extend to **Developer, Product, CSM, Support** packs, each with its own agentic flow
(e.g. Developer: capture requirements → Jira → scan repo → build → verify → PR, with
*approve-then-act* gates). Full implementation-ready spec + sequenced roadmap in
[docs/PLATFORM_EXTENSIBILITY.md](docs/PLATFORM_EXTENSIBILITY.md).
