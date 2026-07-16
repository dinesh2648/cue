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
from types import SimpleNamespace

from sqlalchemy import func, select

from ..advisor import feedback, grounding, insights, meeting_context
from ..advisor.roles import allowed_providers
from ..config import settings
from ..connectors.manager import active_mcp_servers, inprocess_read_tokens
from ..connectors.registry import CONNECTORS
from ..db import SessionLocal
from ..models import AuditLog, Intent, KnowledgeDoc, Meeting, Suggestion, TranscriptSegment, User
from ..packs.registry import get_pack, pack_for_owner, pack_for_team
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
    """Triage one customer turn (user-agnostic), then generate a PERSONALIZED answer for each
    connected participant + the owner, routed to each. Detached from ingestion.

    Triage ("is this a question / what is it") is shared work — done once. The expensive per-user
    part (retrieval + deep answer over THAT person's connectors/role) is fanned out, so two people
    in the same meeting each get answers grounded in their own sources, not one generic answer.
    """
    db = SessionLocal()
    try:
        meeting = db.get(Meeting, meeting_id)
        if meeting is None:
            return
        # Keep the stored pack in sync with the owner's team (UI + summary framing).
        pack_key = pack_for_owner(db, meeting)
        if meeting.pack != pack_key:
            meeting.pack = pack_key
            db.commit()
        pack = get_pack(pack_key)

        # Recent context (last few turns, excluding this one) helps resolve pronouns.
        rows = db.scalars(
            select(TranscriptSegment)
            .where(TranscriptSegment.meeting_id == meeting_id)
            .order_by(TranscriptSegment.ts.desc())
            .limit(7)
        ).all()
        recent = [f"{s.role}: {s.text}" for s in rows if s.id != seg_id][:6][::-1]

        # ── Layer 1: triage ONCE (FR-003) — user-agnostic; shared across participants. ──
        intent_res = await pack.classify(text, recent, meeting_id=meeting_id)
        query = intent_res.query_text or text  # standalone query (pronouns resolved)
        await manager.broadcast(
            meeting_id,
            {"type": "intent", "data": {
                "intent_type": intent_res.intent_type, "family": intent_res.family,
                "confidence": intent_res.confidence, "query_text": query,
                "actionable": intent_res.actionable,
            }},
        )
        if not intent_res.actionable:
            return

        intent_row = Intent(
            meeting_id=meeting_id, segment_id=seg_id, intent_type=intent_res.intent_type,
            query_text=query, confidence=intent_res.confidence,
        )
        db.add(intent_row)
        db.commit()
        intent_id = intent_row.id
        owner_id = meeting.owner_user_id
        # Answer for every connected participant + the owner (owner = canonical record for summary).
        recipients = {
            r for r in (manager.subscriber_ids(meeting_id) | ({owner_id} if owner_id else set())) if r
        }
    except Exception as exc:  # pragma: no cover
        log.exception("triage failed for meeting %s: %s", meeting_id, exc)
        return
    finally:
        db.close()

    if not recipients:
        return
    # Fan out per participant — each in its own DB session for safe concurrency.
    await asyncio.gather(
        *[_answer_for_user(meeting_id, uid, query, intent_res, intent_id, recent) for uid in recipients],
        return_exceptions=True,
    )


async def _answer_for_user(
    meeting_id: str, user_id: str, query: str, intent_res, intent_id: str, recent: list[str]
) -> None:
    """Fast + deep answer grounded in ONE participant's connectors/role/profile, routed to them."""
    db = SessionLocal()
    try:
        meeting = db.get(Meeting, meeting_id)
        if meeting is None:
            return
        user = db.get(User, user_id) if user_id else None
        pack = get_pack(pack_for_team(user.team) if user else pack_for_owner(db, meeting))
        servers = await active_mcp_servers(db, user_id) if user_id else []
        inproc = await inprocess_read_tokens(db, user_id) if user_id else {}
        deep_will_run = pack.has_deep(servers, has_inprocess=any(inproc.values()))
        # Grounding inputs: which of the user's sources are actually connected (friendly names),
        # and which role-relevant tools they're missing (for the honest "connect X" hint).
        connected = {s.get("name", "") for s in servers} | {k for k, v in inproc.items() if v}
        src_names = [CONNECTORS[p].name for p in connected if p in CONNECTORS]
        missing = [
            CONNECTORS[p].name for p in allowed_providers(user)
            if p not in connected and p in CONNECTORS
        ][:3]
        log.info(
            "deep decision meeting=%s user=%s servers=[%s] inproc=[%s] deep_will_run=%s",
            meeting_id, user_id or "(none)",
            ", ".join(s.get("name", "") for s in servers) or "-",
            ", ".join(k for k, v in inproc.items() if v) or "-", deep_will_run,
        )

        # Per-user view: shared meeting-level state, but owner_user_id = THIS participant so the
        # retrieval orchestrator + advisory preamble + role-scoping all key to their own sources.
        mview = SimpleNamespace(
            id=meeting.id, owner_user_id=user_id, crm_company_id=meeting.crm_company_id,
            running_summary=meeting.running_summary, context_json=meeting.context_json,
        )

        t0 = time.perf_counter()
        fast = await pack.fast_answer(db=db, meeting=mview, text=query, intent=intent_res, doc_catalog=_doc_catalog(db))
        fast_latency = int((time.perf_counter() - t0) * 1000)

        # Grounding guardrail (Tier 1): the fast tier only reads seeded/local data, so for a REAL
        # authenticated user it is never *their* data. Show the seeded answer only in zero-cred
        # demo mode; otherwise show a "searching…" placeholder while deep runs, or abstain
        # honestly when nothing can be grounded — never pass off demo CRM as the user's own.
        dev = settings.dev_mode
        if grounding.fast_scope(dev_mode=dev, has_evidence=bool(fast.get("evidence"))) == grounding.DEMO:
            content, scope = fast, grounding.DEMO
        elif deep_will_run:
            content, scope = grounding.researching_answer(src_names), grounding.NONE
        else:
            content, scope = grounding.abstain_answer(missing), grounding.NONE

        sugg = Suggestion(
            meeting_id=meeting_id, recipient_user_id=user_id, intent_id=intent_id,
            intent_type=intent_res.intent_type, query_text=query,
            answer=content["answer"], evidence=content["evidence"], sources=content["sources"],
            actions=content.get("actions", []), confidence=content["confidence"], latency_ms=fast_latency,
            engine="fast" if deep_will_run else "offline", grounded=content.get("grounded", False),
            access_scope=scope,
        )
        db.add(sugg)
        db.add(AuditLog(
            actor="copilot", action="suggestion.fast", resource=meeting_id,
            detail={"user": user_id, "intent": intent_res.intent_type, "latency_ms": fast_latency},
        ))
        db.commit()
        await manager.send_to_user(
            meeting_id, user_id, {"type": "suggestion", "data": _sugg_payload(sugg, deep_pending=deep_will_run)}
        )

        # Tier 2 — deepen over this user's tools + the shared meeting state, then upgrade in place.
        if deep_will_run:
            t1 = time.perf_counter()
            mc = meeting_context.render(mview)
            convo = "\n".join(recent)
            # Feed the user's past corrections back in as authoritative context (feedback loop).
            corrections = feedback.recent_corrections_block(db, user_id)
            full_ctx = "\n\n".join(x for x in [mc, convo, corrections] if x).strip()
            deep = await pack.deep_answer(
                db=db, meeting=mview, text=query, intent=intent_res, servers=servers, context=full_ctx
            )
            deep_latency = int((time.perf_counter() - t1) * 1000)
            sugg.deep_latency_ms = deep_latency

            # Grounding guardrail (Tier 2): a deep answer is only accepted as LIVE if it actually
            # cited the user's sources. If it produced nothing real, don't leave a placeholder —
            # abstain honestly (real user) or fall back to the seeded demo answer (demo mode).
            v = grounding.verify(
                answer=(deep or {}).get("answer", ""), sources=(deep or {}).get("sources"),
                evidence=(deep or {}).get("evidence"),
                scope=grounding.deep_scope(
                    has_sources=bool((deep or {}).get("sources") or (deep or {}).get("evidence")),
                    agent_scope=(deep or {}).get("access_scope"),
                ),
            ) if deep else {"grounded": False, "reason": "deep tier returned nothing"}

            if v["grounded"]:
                sugg.answer = deep["answer"]
                sugg.evidence = deep.get("evidence", [])
                sugg.sources = deep.get("sources", [])
                sugg.confidence = deep.get("confidence", 0.0)
                sugg.engine = deep.get("engine", "claude+mcp")
                sugg.grounded = True
                sugg.access_scope = v["scope"]
                sugg.envelope = {
                    "assumptions": deep.get("assumptions", []),
                    "risks": deep.get("risks", []),
                    "next_actions": deep.get("next_actions", []),
                }
            elif dev:
                sugg.engine = "offline"  # demo mode: keep the seeded fast answer
            else:
                ab = grounding.abstain_answer(missing)
                sugg.answer, sugg.evidence, sugg.sources = ab["answer"], [], []
                sugg.confidence, sugg.grounded, sugg.access_scope = ab["confidence"], False, grounding.NONE
                sugg.engine = "offline"
                log.info("deep not grounded meeting=%s user=%s reason=%s", meeting_id, user_id, v["reason"])
            db.commit()
            await manager.send_to_user(
                meeting_id, user_id, {"type": "suggestion_update", "data": _sugg_payload(sugg, deep_pending=False)}
            )

        # Per-turn trace (observability): one structured line per answer so a degraded turn
        # (abstained / ungrounded / slow / deep failed) is visible in logs, not silent.
        log.info(
            "turn trace meeting=%s user=%s intent=%s engine=%s scope=%s grounded=%s "
            "fast_ms=%s deep_ms=%s sources=%d",
            meeting_id, user_id or "-", intent_res.intent_type, sugg.engine, sugg.access_scope,
            sugg.grounded, sugg.latency_ms, sugg.deep_latency_ms or 0, len(sugg.sources or []),
        )
    except Exception as exc:  # pragma: no cover - one participant's failure must not affect others
        log.exception("answer for user %s (meeting %s) failed: %s", user_id, meeting_id, exc)
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
