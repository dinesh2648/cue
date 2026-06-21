# Frontend — Next.js 15 (App Router) + TypeScript

```bash
npm install
npm run dev        # http://localhost:3000
```

Set the backend URL if it isn't on :8000 — copy `.env.local.example` → `.env.local`
and edit `NEXT_PUBLIC_API_URL`.

## Pages

- `app/page.tsx` — dashboard: hero, "how it works" pipeline, live KPI strip, meeting list,
  **Start demo meeting** (creates the Northwind meeting and opens the live console).
- `app/meeting/[id]/page.tsx` — **live copilot console**: real-time transcript (left),
  streaming suggestion cards (right), and the post-meeting summary + CRM-sync panel.

## Components

- `SuggestionCard.tsx` — confidence ring, intent badge, grounded answer, supporting
  evidence, source chips, and clickable recommended actions.
- `SummaryPanel.tsx` — executive summary, decisions, risks, action items, customer
  concerns, the CRM-updated banner, and a copyable follow-up email draft.

Realtime is a single `WebSocket` to `/ws/meetings/{id}` (see `lib/api.ts`); events
(`transcript` / `intent` / `suggestion` / `status` / `summary`) update the UI live.
