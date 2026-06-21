# Demo Script — AI Sales Meeting Copilot

A tight **5-minute** walkthrough for a prospect. The whole thing runs with **zero
credentials**, so it never fails live. Talking points are in *italics*.

---

## 0 · Setup (before the call, 1 min)

```bash
cd backend  && ./run.sh                 # http://localhost:8000
cd frontend && npm install && npm run dev   # http://localhost:3000
```

Open **http://localhost:3000**. Leave it on the dashboard.
*(Optional “wow” upgrade: if you’re signed into Claude Code, start the backend with
`AGENT_ENGINE=agent_sdk ./run.sh` — answers are then generated live by Claude calling your
tools, and cards show a “Claude · live” badge.)*

---

## 1 · The hook (30 sec) — Dashboard

> *“Reps lose deals in the silence after a hard question — ‘what’s our contract status?’,
> ‘did security pass?’ — because the answer is buried across eight systems. This gives every
> rep a virtual Sales Engineer that answers in seconds, from your own data, and logs the
> follow-up for them.”*

Point at the **“How it works”** pipeline (Listen → Detect → Retrieve → Suggest → Automate)
and the live KPI strip (**&lt;5s SLA**, **100% within SLA**).

Click **▶ Start demo meeting**.

---

## 2 · The live call (2 min) — Meeting console

A simulated Northwind Trading expansion call streams in. Narrate as it happens:

- **Left — live transcript.** *“The copilot is listening to the real conversation, diarized
  by speaker.”* (Customer questions appear on the left, the rep on the right.)
- **Right — suggestions appear within seconds of each customer question.** Pick one card
  (e.g. **Contract Status** or **Security**) and walk through its three parts:
  - **The answer** — *“A ready-to-say response the rep can speak immediately.”*
  - **Supporting evidence + Sources** — *“Every answer is grounded — here are the exact CRM
    fields and the documents it came from. No hallucinations.”*
  - **Confidence ring** — *“And it tells the rep how sure it is.”*
- Point at **Recommended actions** — *“One click to share the SOC 2, start an NDA, or create
  a follow-up task.”*

**Wow moment (if running live Claude):** note a card flip from **“⚡ instant”** to
**“✦ Claude · live”** — *“It answers instantly from cache, then deepens with a full AI agent
that calls your tools live — best of both: fast and thorough.”*

Let it run until all six topics are covered (contract, implementation, security, tickets,
proposal, pricing) — **6 answers, ~93% avg confidence**.

---

## 3 · The payoff (1 min) — End & summarize

Click **⏹ End & summarize**. Scroll to the summary:

- **Executive summary, key decisions, risks, customer concerns, action items.**
- The green **“CRM updated automatically”** banner — *“The rep didn’t touch their CRM. The
  recap note, the follow-up tasks, and a drafted follow-up email were just written back.”*
- Show the **follow-up email draft** — *“Personalized, specific, ready to send.”*

> *“That’s the 30% of admin time we give back per meeting — and the deal momentum you keep.”*

---

## 4 · The trust close (45 sec) — Connections page

Click **🔌 Connections**.

> *“Here’s why security teams say yes: the only secret we hold is the AI key. **Every** tool
> is connected by the **individual rep** with their **own** access — encrypted, used only on
> their behalf. The copilot can only ever see what that person already can. No shared service
> accounts, full audit trail.”*

Point at the six connectors (HubSpot, Drive, Gmail, Calendar, Notion, LinkedIn) and the
per-user **Connect** flow.

---

## Objection handling

| They say | You say |
|---|---|
| *“Will it hallucinate?”* | Every answer is grounded in CRM facts + real docs, with sources and a confidence score shown. It cites or it abstains. |
| *“Is our data safe?”* | Per-user credentials, encrypted at rest, used only on that user’s behalf; access enforced by the source systems. SSO, audit log, GDPR/SOC 2-ready. |
| *“Which meeting platforms?”* | Google Meet today; Zoom & Teams via Recall.ai. Same copilot on all. |
| *“How fast to value?”* | Runs day one with seeded data; a rep connects their tools in minutes and it’s live on their next call. |
| *“What does it integrate with?”* | HubSpot, Drive, Gmail, Calendar, Notion, LinkedIn — and any MCP tool; new connectors are a one-line addition. |

## The three things to leave them with

1. **Instant, grounded, cited answers** in the meeting — not after it.
2. **Automatic CRM hygiene** — notes, tasks, follow-up email, every call.
3. **Permission-correct & safe** — each rep’s own access, nothing shared.
