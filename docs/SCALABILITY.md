# Scalability plan — hundreds of concurrent meetings

Target: **N ≈ 100s of live meetings at once**, each ingesting a transcript, triaging every turn,
and producing **per-participant** answers, plus prep/summary/insights. This documents the current
architecture, the bottlenecks, and a phased plan. It is a roadmap — not all of it is built yet.

## Load model (what actually scales)

Per live meeting, per customer turn:
- 1 × triage (LLM, cheap/fast model) — **shared** across participants (done: triaged once).
- P × {fast answer + deep answer} where **P = connected participants + owner** — the expensive part.
- Every ~6 segments: 1 × meeting-context refresh + 1 × insights pass (throttled).

So cost ≈ `meetings × turns/min × (1 triage + P × deep)`. The deep answer (Anthropic Messages +
MCP tool calls) dominates latency and cost. **The whole plan is about (a) not doing per-user work
we don't need, and (b) moving heavy work off the request path onto horizontally-scalable workers.**

## Current state (single-process)

- **API + WebSockets + agent work all run in one process.** `realtime/engine._schedule` fires agent
  turns as in-process `asyncio` tasks; `realtime/manager` holds WS rooms in memory.
- **Autopilot** is a single in-process loop (`autopilot.run_loop`) that polls calendars + dispatches
  Recall bots + finalizes.
- In-process module state: WS rooms, `_bg_tasks`, prep `_inflight`/`_tasks`, `_running` sets.
- Postgres (prod) via SQLAlchemy; one Recall bot per meeting → one transcript webhook stream.

This is correct and fine for tens of meetings on one box. It will NOT scale to 100s because it's
one process (CPU-bound JSON/So + GIL), in-memory fan-out (can't run >1 replica), and unbounded
concurrent LLM calls.

## Already in place (the seams to scale on)

- **Single fan-out point:** `manager.broadcast()` / `manager.send_to_user()` — swap the body for
  Redis pub/sub and every replica can serve any meeting's sockets.
- **Single "run agent work" point:** `engine._schedule(coro)` — replace with "enqueue job" and a
  worker pool drains it.
- **Shared vs per-user split is done:** triage once; per-user deep only for **connected** users +
  the owner record. Idle meetings (nobody watching) cost ~1 triage + owner record, not P×.
- **Throttled background work:** meeting-context + insights only every `_REFRESH_EVERY` (6) segments.
- **Cheap model for triage** (`TRIAGE_MODEL`), capable model only for deep (`ANTHROPIC_MODEL`).

## Bottlenecks → plan (phased)

### Phase A — horizontal API/WS (unlocks >1 replica)
1. **Redis pub/sub for WS fan-out.** Publish each event to `room:{meeting_id}`; every replica
   subscribes and delivers to its local sockets. `broadcast`/`send_to_user` become publish calls.
2. **Move in-memory state to Redis:** WS room membership (for `subscriber_ids`), prep-inflight,
   `_running`. Makes replicas stateless → put N behind a load balancer with sticky-not-required WS.
3. **Single autopilot dispatcher.** Run the poll/dispatch loop as its own process, or leader-elect
   via a Redis lock, so N replicas don't each dispatch a bot for the same event.

### Phase B — offload agent work to a queue (unlocks worker autoscaling)
4. **Job queue (Arq/Celery/RQ on Redis).** `_schedule` enqueues `{meeting_id, seg_id, text}`;
   a **worker pool** runs triage + per-user fan-out and publishes results via Redis → sockets.
   Web/WS processes stay responsive; scale workers independently by queue depth.
5. **Per-meeting ordering + coalescing.** Key jobs by meeting; drop/merge stale turns under load
   (if 3 turns queue while one is processing, answer the latest). Backpressure per org.
6. **Transcript webhook → queue.** Recall webhook just enqueues the segment; ingestion/persist +
   broadcast happen in a worker. Decouples provider spikes from the API.

### Phase C — LLM cost & latency control (the real spend)
7. **Cache user-agnostic work per turn:** meeting-context render, doc catalog, company/user
   preamble — computed once, reused across participants.
8. **Cache MCP/tool + retrieval results within a meeting** (short TTL) so repeated questions about
   the same account don't re-hit HubSpot/Jira every time.
9. **Concurrency caps + graceful degrade:** cap simultaneous deep answers globally and per org;
   under pressure, serve fast-tier only (offline RAG) and skip deep. Never queue unboundedly.
10. **Per-org quotas / rate limiting** against Anthropic + connector API limits; token-bucket per
    provider; exponential backoff on 429s.
11. **Model tiering:** triage on Haiku; deep on Sonnet/Opus; consider prompt caching for the big
    static system + company/user preamble (it's identical across a meeting's turns).

### Phase D — data & ops
12. **DB:** tune SQLAlchemy pool (per replica × workers ≤ Postgres max_connections; use PgBouncer);
    indexes exist on hot columns (meeting_id, recipient_user_id, share token). Add read replica for
    `/metrics`, `/team`, reporting. Archive/partition `transcript_segments` + `suggestions` by age.
13. **Recording/media:** never proxy media — store + hand out Recall presigned URLs (done).
14. **Observability:** `/metrics` exists (latency p95, SLA %, grounded %); add per-org usage,
    queue depth, worker saturation, LLM spend, and autoscale on queue depth + WS count.
15. **Deploy:** N stateless API replicas + a worker fleet + Redis + managed Postgres behind a LB;
    autoscale API on connections, workers on queue depth. (See DEPLOYMENT.md for the single-box
    Docker setup this evolves from.)

## Guardrails already protecting cost
- Deep tier only when the participant has reachable connectors (else fast/offline).
- Per-user fan-out only for **connected** participants (+ owner record) — not every attendee.
- Insights/context throttled; envelope is a single cheap pass; prep cached per (user, event).

## Rule of thumb for the next build
Anything that (a) holds state in a module global, or (b) does LLM/tool work inline on the request
path, is a scaling blocker. Move (a) to Redis and (b) to the worker queue. The two integration
points — `manager.*` and `engine._schedule` — are deliberately the only places you must change.
