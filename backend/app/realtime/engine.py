"""Live meeting engine: drives the transcript, runs the agent per customer turn,
persists everything, and broadcasts events to subscribed copilot UIs.

Per customer turn it picks the answer engine:
  * Claude + the meeting owner's live MCP connectors (permission-scoped), when available;
  * the offline pipeline (seeded CRM + local retrieval) otherwise.
Intent detection and action recommendations run the same way in both paths.
"""
from __future__ import annotations

import asyncio
import logging
import time

from sqlalchemy import func, select

from ..advisor import insights, meeting_context
from ..connectors.manager import active_mcp_servers, inprocess_read_tokens
from ..db import SessionLocal
from ..models import AuditLog, Intent, KnowledgeDoc, Meeting, Suggestion, TranscriptSegment
from ..packs.registry import get_pack, pack_for_owner
from .manager import manager
from .simulator import get_scenario

log = logging.getLogger("copilot.engine")

_running: set[str] = set()
# Keep references to fire-and-forget agent tasks so they aren't garbage-collected.
_bg_tasks: set[asyncio.Task] = set()


def _schedule(coro) -> None:
    """Run an agent turn in the background so transcript ingestion stays real-time."""
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


def _doc_catalog(db) -> list[dict]:
    docs = db.scalars(select(KnowledgeDoc)).all()
    return [{"id": d.id, "title": d.title, "doc_type": d.doc_type, "url": d.url} for d in docs]


async def process_utterance(
    meeting_id: str, speaker: str, role: str, text: str, ts: float | None = None
) -> None:
    """Persist+broadcast the transcript segment immediately (real-time), then run the
    agent for customer turns in the BACKGROUND so the slow Claude/web loop never delays
    the live transcript or the webhook response.
    """
    # `speaker` comes from the (3rd-party-controlled) Recall webhook; cap it to the column
    # width so a long participant name can't crash the insert with truncation on Postgres.
    speaker = (speaker or "Speaker")[:120]
    text = text or ""

    db = SessionLocal()
    try:
        meeting = db.get(Meeting, meeting_id)
        if meeting is None:
            return

        if ts is None:
            last = db.scalar(
                select(func.max(TranscriptSegment.ts)).where(
                    TranscriptSegment.meeting_id == meeting_id
                )
            )
            ts = (last or 0.0) + 3.0

        seg = TranscriptSegment(meeting_id=meeting_id, speaker=speaker, role=role, text=text, ts=ts)
        db.add(seg)
        db.commit()
        seg_id = seg.id
        seg_count = db.scalar(
            select(func.count(TranscriptSegment.id)).where(TranscriptSegment.meeting_id == meeting_id)
        ) or 0

        await manager.broadcast(
            meeting_id,
            {
                "type": "transcript",
                "data": {"id": seg_id, "speaker": speaker, "role": role, "text": text, "ts": ts},
            },
        )
    finally:
        db.close()

    # Keep the evolving meeting state fresh (every _REFRESH_EVERY segments, from EITHER speaker —
    # decisions/actions come from the rep too), then surface proactive insights. Detached so it
    # never delays ingestion.
    if meeting_context.should_refresh(seg_count):
        _schedule(_update_context_and_insights(meeting_id))

    if role == "customer":
        _schedule(_run_agent_turn(meeting_id, seg_id, text))


async def _update_context_and_insights(meeting_id: str) -> None:
    """Refresh the evolving meeting state, then compute + broadcast proactive insights."""
    await meeting_context.refresh(meeting_id)
    items = await insights.detect(meeting_id)
    if items:
        await manager.broadcast(meeting_id, {"type": "insights", "data": items})


async def _run_agent_turn(meeting_id: str, seg_id: str, text: str) -> None:
    """Intent → two-tier answer for one customer turn. Runs detached from ingestion."""
    db = SessionLocal()
    try:
        meeting = db.get(Meeting, meeting_id)
        if meeting is None:
            return
        # Drive suggestions by the OWNER's current team (Sales vs Tech), and keep the stored
        # pack in sync so the UI + downstream summary/scorecard match.
        pack_key = pack_for_owner(db, meeting)
        if meeting.pack != pack_key:
            meeting.pack = pack_key
            db.commit()
        pack = get_pack(pack_key)

        # ── Layer 1: triage (FR-003) — does this turn need an answer? ────────
        # Recent context (last few turns, excluding this one) helps resolve pronouns.
        rows = db.scalars(
            select(TranscriptSegment)
            .where(TranscriptSegment.meeting_id == meeting_id)
            .order_by(TranscriptSegment.ts.desc())
            .limit(7)
        ).all()
        recent = [f"{s.role}: {s.text}" for s in rows if s.id != seg_id][:6][::-1]

        intent_res = await pack.classify(text, recent)
        query = intent_res.query_text or text  # standalone query (pronouns resolved)
        await manager.broadcast(
            meeting_id,
            {
                "type": "intent",
                "data": {
                    "intent_type": intent_res.intent_type,
                    "family": intent_res.family,
                    "confidence": intent_res.confidence,
                    "query_text": query,
                    "actionable": intent_res.actionable,
                },
            },
        )
        if not intent_res.actionable:
            return

        # ── Two-tier answer (FR-004 → FR-006) ────────────────────────────────
        doc_catalog = _doc_catalog(db)
        servers = (
            await active_mcp_servers(db, meeting.owner_user_id) if meeting.owner_user_id else []
        )
        # In-process sources (Gmail/Drive/Slack) have no hosted MCP but still power a deep answer.
        inproc = (
            await inprocess_read_tokens(db, meeting.owner_user_id) if meeting.owner_user_id else {}
        )
        deep_will_run = pack.has_deep(servers, has_inprocess=any(inproc.values()))

        # Tier 1 — instant grounded answer (the SLA-critical path).
        t0 = time.perf_counter()
        fast = await pack.fast_answer(
            db=db, meeting=meeting, text=query, intent=intent_res, doc_catalog=doc_catalog
        )
        fast_latency = int((time.perf_counter() - t0) * 1000)

        intent_row = Intent(
            meeting_id=meeting_id,
            segment_id=seg_id,
            intent_type=intent_res.intent_type,
            query_text=query,
            confidence=intent_res.confidence,
        )
        db.add(intent_row)
        db.commit()

        sugg = Suggestion(
            meeting_id=meeting_id,
            intent_id=intent_row.id,
            intent_type=intent_res.intent_type,
            query_text=query,
            answer=fast["answer"],
            evidence=fast["evidence"],
            sources=fast["sources"],
            actions=fast["actions"],
            confidence=fast["confidence"],
            latency_ms=fast_latency,
            engine="fast" if deep_will_run else "offline",
            grounded=fast.get("grounded", True),
            access_scope="demo",  # fast tier = local CRM/retrieval
        )
        db.add(sugg)
        db.add(
            AuditLog(
                actor="copilot",
                action="suggestion.fast",
                resource=meeting_id,
                detail={"intent": intent_res.intent_type, "latency_ms": fast_latency},
            )
        )
        db.commit()

        await manager.broadcast(
            meeting_id,
            {"type": "suggestion", "data": _sugg_payload(sugg, deep_pending=deep_will_run)},
        )

        # Tier 2 — deepen with the Claude agentic loop, then upgrade the card in place.
        if deep_will_run:
            t1 = time.perf_counter()
            # Prepend the evolving meeting state so the answer reasons over the WHOLE meeting
            # (decisions, open questions, entities), not just the last few lines.
            mc = meeting_context.render(meeting)
            convo = "\n".join(recent)
            full_ctx = f"{mc}\n\n{convo}".strip() if mc else convo
            deep = await pack.deep_answer(
                db=db, meeting=meeting, text=query, intent=intent_res, servers=servers,
                context=full_ctx,
            )
            deep_latency = int((time.perf_counter() - t1) * 1000)
            if deep:
                sugg.answer = deep["answer"]
                sugg.evidence = deep["evidence"]
                sugg.sources = deep["sources"]
                sugg.confidence = deep["confidence"]
                sugg.engine = deep.get("engine", "claude+mcp")
                sugg.deep_latency_ms = deep_latency
                sugg.grounded = deep.get("grounded", True)
                sugg.access_scope = deep.get("access_scope", "demo")
                sugg.envelope = {
                    "assumptions": deep.get("assumptions", []),
                    "risks": deep.get("risks", []),
                    "next_actions": deep.get("next_actions", []),
                }
            else:
                sugg.engine = "offline"  # deep failed; keep the fast answer
            db.commit()
            await manager.broadcast(
                meeting_id,
                {"type": "suggestion_update", "data": _sugg_payload(sugg, deep_pending=False)},
            )
    except Exception as exc:  # pragma: no cover - background task must not crash silently
        log.exception("agent turn failed for meeting %s: %s", meeting_id, exc)
    finally:
        db.close()


def _sugg_payload(sugg: Suggestion, *, deep_pending: bool) -> dict:
    return {
        "id": sugg.id,
        "intent_type": sugg.intent_type,
        "query_text": sugg.query_text,
        "answer": sugg.answer,
        "evidence": sugg.evidence,
        "sources": sugg.sources,
        "actions": sugg.actions,
        "confidence": sugg.confidence,
        "latency_ms": sugg.latency_ms,
        "deep_latency_ms": sugg.deep_latency_ms,
        "engine": sugg.engine,
        "grounded": sugg.grounded,
        "access_scope": sugg.access_scope,
        "envelope": sugg.envelope or {},
        "deep_pending": deep_pending,
        "created_at": sugg.created_at.isoformat(),
    }


async def _run(meeting_id: str, scenario_name: str | None) -> None:
    db = SessionLocal()
    try:
        meeting = db.get(Meeting, meeting_id)
        if meeting:
            meeting.status = "live"
            db.commit()
    finally:
        db.close()

    await manager.broadcast(meeting_id, {"type": "status", "data": {"status": "live"}})

    scenario = get_scenario(scenario_name)
    ts = 0.0
    try:
        for turn in scenario:
            await asyncio.sleep(turn["delay"])
            ts += turn["delay"]
            await process_utterance(meeting_id, turn["speaker"], turn["role"], turn["text"], ts=ts)
        await manager.broadcast(
            meeting_id, {"type": "status", "data": {"status": "transcript_complete"}}
        )
    except Exception as exc:  # pragma: no cover
        log.exception("meeting run failed: %s", exc)
        await manager.broadcast(meeting_id, {"type": "error", "data": {"message": str(exc)}})
    finally:
        _running.discard(meeting_id)


def start_meeting(meeting_id: str, scenario_name: str | None = None) -> bool:
    """Spawn the live meeting task. Returns False if already running."""
    if meeting_id in _running:
        return False
    _running.add(meeting_id)
    try:
        asyncio.create_task(_run(meeting_id, scenario_name))
    except RuntimeError:
        _running.discard(meeting_id)
        raise
    return True


def is_running(meeting_id: str) -> bool:
    return meeting_id in _running
