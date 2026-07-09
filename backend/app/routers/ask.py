"""Ask endpoint — query the copilot outside a meeting.

Runs the SAME pack two-tier flow the live meeting engine uses (fast offline answer →
deep agentic answer over the user's own connected sources), but for an ad-hoc question
from the signed-in user. Doubles as a connector test bench: the response reports which
sources were available and which the agent actually used.
"""
from __future__ import annotations

import logging
import time
from types import SimpleNamespace

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..connectors import live_sources
from ..connectors.manager import active_mcp_servers, inprocess_read_tokens
from ..db import get_db
from ..models import KnowledgeDoc, Meeting, TranscriptSegment, User
from ..packs.registry import get_pack, pack_for_team
from ..security.auth import get_current_user, visible_user_ids

log = logging.getLogger("copilot.ask")
router = APIRouter(prefix="/api/ask", tags=["ask"])


class AskRequest(BaseModel):
    query: str
    context: str = ""  # optional prior turns, so follow-ups resolve ("what about that repo?")
    meeting_id: str | None = None  # live in-meeting Ask — grounds the answer in the meeting


def _doc_catalog(db: Session) -> list[dict]:
    docs = db.scalars(select(KnowledgeDoc)).all()
    return [{"id": d.id, "title": d.title, "doc_type": d.doc_type, "url": d.url} for d in docs]


@router.post("")
async def ask(
    body: AskRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    query = (body.query or "").strip()
    if not query:
        return {
            "answer": "Ask a question and I'll research it across your connected sources.",
            "evidence": [], "sources": [], "confidence": 0.0, "engine": "none",
            "grounded": False, "persona": "sales", "intent": "general",
            "connected": [], "used": [], "deep_ran": False, "latency_ms": 0,
        }

    t0 = time.perf_counter()
    # Same pack the user's meetings use — resolved from their current team (sales↔tech).
    pack = get_pack(pack_for_team(user.team))
    persona = "tech" if pack.manifest.key == "tech" else "sales"
    recent = [ln for ln in (body.context or "").splitlines() if ln.strip()] or None
    intent = await pack.classify(query, recent)

    # Retrieval always runs as the CURRENT user (their tools). For an in-meeting Ask we also attach
    # the meeting's evolving state + recent transcript so "what did we decide?" is grounded.
    ctx = SimpleNamespace(owner_user_id=user.id, crm_company_id=None, id=None, pack=pack.manifest.key,
                          running_summary="", context_json={})
    extra_context = body.context or ""
    if body.meeting_id:
        meeting = db.get(Meeting, body.meeting_id)
        if meeting is not None and (
            meeting.owner_user_id in visible_user_ids(db, user)
            or (user.email and user.email in (meeting.attendees or []))
        ):
            ctx.crm_company_id = meeting.crm_company_id
            ctx.running_summary = meeting.running_summary or ""
            ctx.context_json = meeting.context_json or {}
            segs = list(db.scalars(
                select(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting.id)
                .order_by(TranscriptSegment.ts.desc()).limit(14)
            ))
            if segs:
                convo = "\n".join(f"{s.speaker} ({s.role}): {s.text}" for s in reversed(segs))
                extra_context = (f"Recent meeting transcript:\n{convo}\n\n{extra_context}").strip()
    servers = await active_mcp_servers(db, user.id)
    inproc = await inprocess_read_tokens(db, user.id)

    # Tier 1 — instant offline answer (internal knowledge docs + CRM).
    try:
        fast = await pack.fast_answer(
            db=db, meeting=ctx, text=query, intent=intent, doc_catalog=_doc_catalog(db)
        )
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("ask fast_answer failed: %s", exc)
        fast = {"answer": "", "evidence": [], "sources": [], "confidence": 0.0}

    # Tier 2 — deep agentic answer over the user's live connected sources.
    deep = None
    if pack.has_deep(servers, has_inprocess=any(inproc.values())):
        try:
            deep = await pack.deep_answer(
                db=db, meeting=ctx, text=query, intent=intent,
                servers=servers, context=extra_context,
            )
        except Exception as exc:
            log.warning("ask deep_answer failed: %s", exc)

    best = deep or fast
    # "Searched" = remote-MCP servers (agent tools) + the in-process sources gather_comms queries
    # (Gmail/Drive/Slack/Notion-PAT/Calendar) — the latter aren't in `servers`, so add them here.
    searched = [s.get("name") for s in servers] + (
        await live_sources.available_inprocess(db, user.id) if deep else []
    )
    return {
        "answer": best.get("answer") or "I couldn't find an answer in your connected sources.",
        "evidence": best.get("evidence", []),
        "sources": best.get("sources", []),
        "confidence": best.get("confidence", 0.0),
        "engine": best.get("engine", "deep" if deep else "fast"),
        "grounded": best.get("grounded", False),
        "assumptions": best.get("assumptions", []),
        "risks": best.get("risks", []),
        "next_actions": best.get("next_actions", []),
        "persona": persona,
        "intent": intent.intent_type,
        "connected": searched,  # every source searched: remote-MCP servers + in-process sources
        "used": [s.get("label") for s in best.get("sources", [])],  # sources it actually cited
        "deep_ran": bool(deep),
        "latency_ms": int((time.perf_counter() - t0) * 1000),
    }
