# Platform Extensibility — From Sales Pilot to Multi-Vertical Agentic Copilots

**Status:** Plan (not yet built). Sales is the shipped pilot. This document is the
implementation-ready spec for extending the platform to additional personas
(Developer, Product, CSM, Support…), each with its own agentic flow.

**Chosen autonomy model:** *Approve-then-act* — the agent proposes every write action
(ticket, commit, PR, email); a human approves before it executes. Full audit trail.

---

## 1. Principle: one substrate, many packs

The product is **not** "a sales tool." It's a meeting-aware agentic substrate with
**pluggable Copilot Packs**. A pack is a vertical (Sales, Developer, Product…). ~80% of
the platform is shared; only the *triggers, tools, flow, and actions* differ per pack.

```
┌─────────────────────── SHARED SUBSTRATE (built today) ────────────────────────┐
│ Meeting capture (Recall.ai / simulator) · live transcript · realtime WS         │
│ Clerk SSO · per-user MCP connectors · OAuth + encrypted token vault · audit log │
│ Agent runtime (Claude Agent SDK + Anthropic MCP) · two-tier latency             │
│ Action/approval framework · multi-tenant scoping                                │
└──────────────────────────────────┬──────────────────────────────────────────────┘
        ┌──────────────┬────────────┴───────────┬──────────────────┐
   ┌────▼────┐    ┌────▼─────┐           ┌───────▼──────┐    ┌──────▼──────┐
   │  SALES  │    │ DEVELOPER│           │   PRODUCT    │    │     CSM     │   Copilot Packs
   └─────────┘    └──────────┘           └──────────────┘    └─────────────┘
```

Multiple packs can attach to the same meeting and each surfaces to its own owner (e.g.
a Developer on a call with a Product team runs the Developer pack; a Sales rep on the
same call runs the Sales pack).

---

## 2. The Copilot Pack contract

A pack is a declarative profile + a flow. Adding a vertical = adding one pack.

```python
@dataclass
class CopilotPack:
    key: str                      # "sales" | "developer" | "product" | "csm"
    name: str
    persona: str                  # the role this pack serves
    triggers: IntentSet           # what moments it reacts to (its intent taxonomy)
    tools: list[str]              # required connector keys (e.g. ["github","jira"])
    flow: FlowSpec                # inline graph + optional async workflow (see §4)
    actions: list[ActionSpec]     # executable actions, each with autonomy metadata
    surfaces: list[Surface]       # how its output renders (cards, ticket/PR chips…)
    default_autonomy: str = "approve"   # suggest | approve | auto

@dataclass
class ActionSpec:
    key: str                      # "create_jira_ticket", "open_pr", "share_document"…
    label: str
    kind: str                     # ticket | pr | build | document | email | task | workflow
    write: bool                   # write/irreversible → routed through approval
    connector: str | None         # which connector executes it (user's own auth)
    autonomy: str | None = None    # overrides pack default for this action
```

**Pack registry** mirrors the existing connector registry (`connectors/registry.py`):
`packs/registry.py` with one module per pack under `packs/<key>/`.

---

## 3. How today's Sales app becomes a pack (refactor path, no behavior change)

The current code already separates cleanly — the refactor is mechanical:

| Today (Sales-specific, hardcoded) | Becomes |
|---|---|
| `agent/intent.py` keyword sets | `packs/sales/triggers.py` (Sales `IntentSet`) |
| `agent/retrieval.py` + `answer.py` + `actions.py` | `packs/sales/flow.py` (the Sales inline graph) |
| `agent/actions.py` action map | `packs/sales/actions.py` (`ActionSpec[]`) |
| `realtime/engine.py` `_fast_answer/_deep_answer` | substrate calls `pack.flow.inline(state)` |
| `agent/claude_sdk.py` / `claude_agent.py` | shared runtime, unchanged |

So `engine.process_utterance` becomes pack-agnostic: detect the meeting's pack(s) →
`pack.triggers.detect(text)` → `pack.flow.inline(...)` → render `pack.surfaces`.

---

## 4. Two execution modes

Different verticals need different time horizons. The substrate runs both.

### 4a. Inline (real-time) — the Sales hot path, already built
`triggers.detect → flow.inline(state)` on each customer turn, two-tier (instant grounded
answer < 5s, deep Claude+MCP upgrade in place). Best for *assist-in-the-moment* packs.

### 4b. Workflow (async, autonomous) — new, needed for Developer
Longer multi-step jobs that run during/after the call, durably, with progress + approval
gates. A `FlowSpec.workflow` is a DAG of steps:

```python
workflow = Workflow([
    Step("capture_requirements",  inline=True),                 # runs live
    Step("create_jira",           write=True, gate="approve"),  # pauses for approval
    Step("scan_repo"),
    Step("implement",             agent="coding"),              # Claude coding agent
    Step("verify"),                                             # tests/lint, fix-loop
    Step("open_pr",               write=True, gate="approve"),
    Step("notify"),
])
```

**Engine:** durable orchestration via **Temporal** (recommended) or a job queue
(RQ/Celery) — retries, resumability, per-step state, and human-in-the-loop pauses for
approval gates. Progress streams to the meeting UI / Slack over the existing WS.

---

## 5. Action & approval framework (approve-then-act)

Reads and suggestions run freely. Every **write** action is proposed, not executed,
until a human approves.

```
agent proposes ─▶ ProposedAction(status=proposed) ─▶ UI/Slack approval
                                                          │ approve            │ reject
                                                          ▼                    ▼
                                            execute via user's connector    discard
                                                          ▼
                                            audit + result (ticket/PR link)
```

New model + endpoints:

```python
class ProposedAction(Base):           # new table
    id, meeting_id, pack, action_key, payload(JSON)
    status: str   # proposed | approved | rejected | executed | failed
    approver: str | None
    result: dict  # external ids / links
    created_at, decided_at
```
```
GET  /api/meetings/{id}/actions            # pending + history
POST /api/actions/{action_id}/approve      # executes via the connector, audits
POST /api/actions/{action_id}/reject
```

UI: an **Approvals** strip in the meeting console (and optional Slack approve button).
This framework is reusable by Sales too (e.g. gate "send proposal email").

---

## 6. Worked example — the Developer pack

**Persona:** a developer on a call with a Product team.
**Tools:** `github`, `jira`, `confluence`, `slack`, `ci` (all per-user OAuth/MCP, same model as today).

### Inline (during the call)
`triggers`: detect *requirement · decision · acceptance-criterion · risk · scope-change*.
Surface a live card per captured requirement:
> 📋 **Requirement captured** — "Users can export reports as CSV"
> _Acceptance: handles 1M+ rows; async if >30s_ · **[Create ticket]**

### Async workflow (post-call, approve-then-act gates in **bold**)
1. **`create_jira`** — epic + stories from captured requirements *(Jira MCP, dev's auth)* — **approval gate**
2. `scan_repo` — locate relevant modules, build code context *(GitHub MCP)*
3. `implement` — spawn a **Claude coding agent in an isolated git worktree** (the Claude
   Agent SDK we already use, in build mode): reads the repo, writes the change
4. `verify` — run tests / lint / build; fix-loop until green (bounded retries)
5. **`open_pr`** — draft PR linked to the Jira ticket *(GitHub MCP)* — **approval gate**
6. `notify` — post PR + ticket links to the meeting summary and Slack, request review

Result the developer sees: a Jira epic, a green draft PR, and links — from a conversation
they were having, with two approval clicks. This is the PRD's Phase 3 autonomy, scoped to
a dev persona.

> **Coding-agent safety:** runs in a throwaway git worktree/branch, never on `main`, never
> deploys; PRs are draft; all writes gated. Sandbox + resource/time limits on the agent.

---

## 7. Other verticals (sketch)

| Pack | Triggers | Tools | Signature actions (gated) |
|---|---|---|---|
| **Product** | feature ask, feedback, prioritization, roadmap Q | Jira, Linear, Notion, Amplitude | create story, update roadmap, log feedback |
| **CSM / Success** | health risk, renewal, escalation, adoption | CRM, Zendesk, Gainsight, Calendar | open CTA, schedule QBR, draft exec summary |
| **Support / SE** | incident, config, how-to, bug | Zendesk, Jira, GitHub, Confluence, PagerDuty | create incident, link KB, draft RCA |

Each is one `CopilotPack` + its connectors — no substrate changes.

---

## 8. Connector roadmap

Built: HubSpot · Google Drive · Gmail · Google Calendar · Notion · LinkedIn.
Add (same per-user OAuth/MCP pattern, one registry entry each):
**GitHub · Jira/Atlassian · Confluence · Slack · Linear · Zendesk · PagerDuty · CI**.
Most have hosted MCP servers or OAuth apps; the rest get thin API adapters.

---

## 9. Sequenced roadmap

| Phase | Scope | Rough effort |
|---|---|---|
| **A** | Extract the **Pack abstraction**; move Sales into `packs/sales/` (no behavior change) | S |
| **B** | **Action/approval framework** (`ProposedAction` + approve/reject API + Approvals UI); retrofit Sales writes | S–M |
| **C** | **Async workflow engine** (Temporal or queue) + WS progress + gate pauses | M |
| **D** | **Developer connectors** (GitHub, Jira, Confluence, Slack, CI) | M |
| **E** | **Developer pack** — inline requirement capture + async Jira→repo→code→verify→PR with gates + coding agent in worktree | L |
| **F** | **Product / CSM / Support packs** (each ≈ one pack + connectors) | M each |
| **G** | **Pack routing** — auto-assign packs by participant role / agenda; multi-pack per meeting | S |

Start at **A → B** (pure refactor + the approval primitive) — both improve the Sales pilot
immediately and unlock everything else.

---

## 10. What's reused vs. new

**Reused unchanged:** meeting capture · transcript · realtime WS · Clerk SSO · per-user MCP
connectors · token vault · audit log · agent runtime (Claude Agent SDK + MCP) · two-tier
latency · UI shell.

**New:** pack registry + per-pack triggers/flows/actions · async workflow engine ·
coding-agent-in-worktree · approval/ProposedAction framework · developer/other connectors ·
pack routing.

The bet: every new vertical is **a pack + a few connectors**, not a new product.
