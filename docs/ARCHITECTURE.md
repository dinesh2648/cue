# Architecture

## System overview

```
                    ┌───────────────────────── Browser (Next.js) ─────────────────────────┐
                    │  Dashboard  │  Live console: transcript · suggestions · summary       │
                    └───────▲───────────────────────▲───────────────────────▲──────────────┘
                       REST │                     WS │ (live events)   REST  │
                            │                        │                       │
        ┌───────────────────┴────────────────────────┴───────────────────────┴────────────┐
        │                                  FastAPI backend                                  │
        │                                                                                   │
        │  routers/ ── meetings · knowledge · crm        realtime/ ── engine · manager(WS)  │
        │                          │                                  │                      │
        │                          ▼                                  ▼                      │
        │             agent/ LangGraph StateGraph          simulator (Google Meet stand-in) │
        │   START → intent → retrieve → answer → actions → END                              │
        │                 │          │         │                                            │
        │                 │   ┌──────┴───────┐ │                                            │
        │                 │   ▼              ▼ ▼                                            │
        │        knowledge/store      integrations/hubspot     integrations/llm            │
        │      (TF-IDF | embeddings)   (mock DB ↔ HubSpot)   (offline | Anthropic/OpenAI)   │
        └───────────────────────────────────┬───────────────────────────────────────────── ┘
                                             ▼
                              SQLAlchemy → SQLite (default) | PostgreSQL
```

## Request lifecycle (a customer turn)

1. **Capture** — the simulator (or a real Meet bot) emits a diarized segment; the engine
   persists it and broadcasts a `transcript` event.
2. **Intent** (FR-003) — for customer turns, `detect_intent` scores the utterance against
   weighted keyword groups → `{intent_type, family, confidence}`. Sub-millisecond, offline.
3. **Route** — low-confidence / smalltalk turns short-circuit to END (no suggestion noise).
4. **Retrieve** (FR-004) — `extract_crm_facts` pulls intent-relevant fields from the HubSpot
   snapshot; `knowledge.store` returns ranked document snippets (relevance-floored).
5. **Answer** (FR-005) — a deterministic composer builds a grounded, rep-ready response with
   evidence, source attribution, and a confidence score derived from intent strength +
   retrieval quality + CRM coverage. An LLM, if configured, only *polishes the wording*.
6. **Actions** (FR-006) — the intent maps to next-best-actions, wired to the actual seeded
   documents (e.g. security → SOC 2 + whitepaper + NDA workflow).
7. **Broadcast** — `intent` then `suggestion` events stream to every subscribed console.
8. **End** (FR-007) — `generate_summary` produces the executive summary, decisions, risks,
   action items, concerns, and a follow-up email; CRM automation writes a recap note, tasks,
   and the email draft back to HubSpot.

## Data model (SQLAlchemy)

`Meeting` 1─*  `TranscriptSegment` · `Intent` · `Suggestion`, 1─1 `MeetingSummary`.
`CRMObject` (company/contact/deal/ticket/task/note) and `KnowledgeDoc` hold the seeded
HubSpot + Drive data and AI-created records. `CRMSyncRecord` logs every write-back;
`AuditLog` records material actions (security requirement).

## The agent graph

`app/agent/graph.py` is a ~90-line async `StateGraph` implementing the slice of the
`langgraph` API the pipeline uses (`add_node` / `add_edge` / `add_conditional_edges` /
`set_entry_point` / `compile().ainvoke`). Node code is written to LangGraph conventions
(each node returns a partial state dict that is merged), so moving to the real `langgraph`
package is a one-line import swap with **zero node changes**.

## Design principle: offline-first, production-ready

Every external dependency has a graceful local fallback, so the product runs with zero
credentials yet upgrades cleanly:

| Concern | Offline default | Production (env-flipped) |
|---|---|---|
| Storage | SQLite | PostgreSQL (`DATABASE_URL`) |
| Vector search | in-process TF-IDF cosine | OpenAI embeddings → Qdrant (`QDRANT_URL`) |
| Generation | deterministic composer | Anthropic / OpenAI (`*_API_KEY`) |
| CRM | seeded mock table | HubSpot API (`HUBSPOT_TOKEN`) |
| Enterprise docs | seeded Drive docs | Google Drive (`GOOGLE_CREDENTIALS_JSON`) |
| Realtime fan-out | in-process WS rooms | Redis Streams (`REDIS_URL`) |
| Meeting capture | scripted simulator | Google Meet bot → same WS interface |

## Security posture (PRD requirements)

- **RBAC** — persona roles (Sales Exec / AM / SE / CSM) model the access surface.
- **Audit logging** — `AuditLog` captures meeting + suggestion + write-back events.
- **PII redaction** — supported as a transcript/log transform hook (documented in
  the security whitepaper seed) ahead of full enforcement.
- **Encryption / SSO / GDPR / SOC 2** — scoped as deployment concerns; SSO/RBAC/AES-256
  are the next integration items (see Roadmap).

## Roadmap mapping to the PRD

- **Phase 1 (this build)** — Google Meet (simulated), HubSpot + Drive retrieval, suggested
  answers, summary, CRM automation.
- **Phase 2** — real Meet/Teams/Zoom bots, Salesforce/Confluence/Jira/Notion connectors,
  battlecards, renewal-risk + buying-signal detection (new agent nodes on the same graph).
- **Phase 3** — autonomous actions (auto-update CRM, schedule follow-ups, create Jira
  tickets, generate proposals/SOWs/decks) — extend `actions.py` from *recommend* to *execute*.
