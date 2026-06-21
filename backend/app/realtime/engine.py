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

from ..agent import claude_agent, claude_sdk
from ..agent.intent import detect_intent
from ..agent.pipeline import pipeline
from ..connectors.manager import active_mcp_servers
from ..db import SessionLocal
from ..integrations import hubspot
from ..models import AuditLog, Intent, KnowledgeDoc, Meeting, Suggestion, TranscriptSegment
from .manager import manager
from .simulator import get_scenario

log = logging.getLogger("copilot.engine")

_running: set[str] = set()


def _doc_catalog(db) -> list[dict]:
    docs = db.scalars(select(KnowledgeDoc)).all()
    return [{"id": d.id, "title": d.title, "doc_type": d.doc_type, "url": d.url} for d in docs]


async def _fast_answer(db, meeting, text: str, doc_catalog: list[dict]) -> dict:
    """Tier 1 (<5s SLA): instant grounded answer from local CRM + retrieval."""
    crm_context = hubspot.company_context(db, meeting.crm_company_id)
    result = await pipeline.ainvoke(
        {"query_text": text, "crm_context": crm_context, "doc_catalog": doc_catalog}
    )
    return {
        "answer": result.get("answer", ""),
        "evidence": result.get("evidence", []),
        "sources": result.get("sources", []),
        "confidence": result.get("confidence", 0.0),
        "actions": result.get("actions", []),
    }


async def _deep_answer(db, meeting, text: str, intent_type: str, servers: list[dict]) -> dict | None:
    """Tier 2: full Claude agentic loop over MCP tools (richer, ~10-15s)."""
    if claude_sdk.available():
        return await claude_sdk.run_turn(text, intent_type, meeting.crm_company_id)
    if claude_agent.available() and servers:
        return await claude_agent.run_turn(text, intent_type, servers)
    return None


async def process_utterance(
    meeting_id: str, speaker: str, role: str, text: str, ts: float | None = None
) -> None:
    """Persist one transcript segment and, for customer turns, run the agent."""
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

        await manager.broadcast(
            meeting_id,
            {
                "type": "transcript",
                "data": {"id": seg.id, "speaker": speaker, "role": role, "text": text, "ts": ts},
            },
        )

        if role != "customer":
            return

        # ── Intent (FR-003) ──────────────────────────────────────────────────
        intent_res = detect_intent(text)
        await manager.broadcast(
            meeting_id,
            {
                "type": "intent",
                "data": {
                    "intent_type": intent_res.intent_type,
                    "family": intent_res.family,
                    "confidence": intent_res.confidence,
                    "query_text": text,
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
        deep_will_run = claude_sdk.available() or (claude_agent.available() and bool(servers))

        # Tier 1 — instant grounded answer (the SLA-critical path).
        t0 = time.perf_counter()
        fast = await _fast_answer(db, meeting, text, doc_catalog)
        fast_latency = int((time.perf_counter() - t0) * 1000)

        intent_row = Intent(
            meeting_id=meeting_id,
            segment_id=seg.id,
            intent_type=intent_res.intent_type,
            query_text=text,
            confidence=intent_res.confidence,
        )
        db.add(intent_row)
        db.commit()

        sugg = Suggestion(
            meeting_id=meeting_id,
            intent_id=intent_row.id,
            intent_type=intent_res.intent_type,
            query_text=text,
            answer=fast["answer"],
            evidence=fast["evidence"],
            sources=fast["sources"],
            actions=fast["actions"],
            confidence=fast["confidence"],
            latency_ms=fast_latency,
            engine="fast" if deep_will_run else "offline",
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
            deep = await _deep_answer(db, meeting, text, intent_res.intent_type, servers)
            deep_latency = int((time.perf_counter() - t1) * 1000)
            if deep:
                sugg.answer = deep["answer"]
                sugg.evidence = deep["evidence"]
                sugg.sources = deep["sources"]
                sugg.confidence = deep["confidence"]
                sugg.engine = deep.get("engine", "claude+mcp")
                sugg.deep_latency_ms = deep_latency
            else:
                sugg.engine = "offline"  # deep failed; keep the fast answer
            db.commit()
            await manager.broadcast(
                meeting_id,
                {"type": "suggestion_update", "data": _sugg_payload(sugg, deep_pending=False)},
            )
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
