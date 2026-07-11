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

from ..advisor import feedback, grounding
from ..advisor.roles import allowed_providers
from ..config import settings
from ..connectors import live_sources
from ..connectors.manager import active_mcp_servers, inprocess_read_tokens
from ..connectors.registry import CONNECTORS
from ..db import get_db
from ..models import KnowledgeDoc, Meeting, Suggestion, TranscriptSegment, User
from ..packs.registry import get_pack, pack_for_team
from ..security.auth import get_current_user, visible_user_ids

log = logging.getLogger("copilot.ask")
router = APIRouter(prefix="/api/ask", tags=["ask"])


class AskRequest(BaseModel):
    query: str
    context: str = ""  # optional prior turns, so follow-ups resolve ("what about that repo?")
    meeting_id: str | None = None  # live in-meeting Ask — grounds the answer in the meeting
    selection: list[str] = []  # transcript lines the user tagged to ask specifically about


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
            # The whole-meeting summary + decisions/entities ride in via the meeting state below;
            # here we stack the specific context: tagged lines → earlier answers → recent transcript.
            ctx.running_summary = meeting.running_summary or ""
            ctx.context_json = meeting.context_json or {}
            parts: list[str] = []
            # 1) Lines the user tagged — what they're asking *about*, front and center.
            sel = [s.strip() for s in (body.selection or []) if s and s.strip()][:20]
            if sel:
                parts.append(
                    "The user tagged these lines from the transcript and is asking specifically "
                    "about them:\n" + "\n".join(f"> {s[:400]}" for s in sel)
                )
            # 2) Earlier copilot answers this meeting, so follow-ups build on them (not repeat).
            prior = list(db.scalars(
                select(Suggestion).where(Suggestion.meeting_id == meeting.id)
                .order_by(Suggestion.created_at.desc()).limit(8)
            ))
            qa = "\n".join(f"Q: {s.query_text}\nA: {s.answer[:300]}" for s in reversed(prior) if s.answer)
            if qa:
                parts.append("Earlier answers the copilot already gave in this meeting:\n" + qa)
            # 3) Recent transcript (wide window; the running summary above covers the rest).
            segs = list(db.scalars(
                select(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting.id)
                .order_by(TranscriptSegment.ts.desc()).limit(40)
            ))
            if segs:
                convo = "\n".join(f"{s.speaker} ({s.role}): {s.text}" for s in reversed(segs))
                parts.append(f"Recent meeting transcript:\n{convo}")
            if body.context:
                parts.append(body.context)
            extra_context = "\n\n".join(parts).strip()
    # Feed the user's past corrections back in as authoritative context (feedback loop).
    corrections = feedback.recent_corrections_block(db, user.id)
    if corrections:
        extra_context = (f"{extra_context}\n\n{corrections}".strip() if extra_context else corrections)

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

    # Grounding guardrail: accept the deep answer only if it actually cited the user's sources
    # (LIVE); else the seeded fast answer only in demo mode (DEMO); else abstain honestly (NONE)
    # rather than pass off seeded CRM as the user's data.
    dev = settings.dev_mode
    connected_set = {s.get("name", "") for s in servers} | {k for k, v in inproc.items() if v}
    missing = [
        CONNECTORS[p].name for p in allowed_providers(user)
        if p not in connected_set and p in CONNECTORS
    ][:3]
    deep_v = grounding.verify(
        answer=(deep or {}).get("answer", ""), sources=(deep or {}).get("sources"),
        evidence=(deep or {}).get("evidence"),
        scope=grounding.deep_scope(
            has_sources=bool((deep or {}).get("sources") or (deep or {}).get("evidence")),
            agent_scope=(deep or {}).get("access_scope"),
        ),
    ) if deep else {"grounded": False, "scope": grounding.NONE}
    if deep and deep_v["grounded"]:
        best, scope = deep, deep_v["scope"]
    elif grounding.fast_scope(dev_mode=dev, has_evidence=bool(fast.get("evidence"))) == grounding.DEMO:
        best, scope = fast, grounding.DEMO
    else:
        best, scope = grounding.abstain_answer(missing), grounding.NONE

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
        "access_scope": scope,
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
