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

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..advisor import feedback, grounding
from ..advisor.roles import allowed_providers
from ..config import settings
from ..connectors import live_sources
from ..connectors.manager import active_mcp_servers, inprocess_read_tokens
from ..connectors.registry import CONNECTORS
from ..db import get_db
from ..models import AskMessage, AskThread, KnowledgeDoc, Meeting, Suggestion, TranscriptSegment, User
from ..packs.registry import get_pack, pack_for_team
from ..security.auth import get_current_user, visible_user_ids

log = logging.getLogger("copilot.ask")
router = APIRouter(prefix="/api/ask", tags=["ask"])


class AskRequest(BaseModel):
    query: str
    context: str = ""  # optional prior turns, so follow-ups resolve ("what about that repo?")
    meeting_id: str | None = None  # live in-meeting Ask — grounds the answer in the meeting
    selection: list[str] = []  # transcript lines the user tagged to ask specifically about
    thread_id: str | None = None  # the Ask conversation this turn belongs to (created if absent)


class ThreadCreate(BaseModel):
    title: str | None = None


class ThreadRename(BaseModel):
    title: str


def _thread_out(t: AskThread) -> dict:
    return {"id": t.id, "title": t.title, "updated_at": t.updated_at.isoformat() if t.updated_at else ""}


@router.get("/threads")
def list_threads(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """The signed-in user's Ask conversations, most-recently-active first."""
    rows = db.scalars(
        select(AskThread).where(AskThread.user_id == user.id).order_by(AskThread.updated_at.desc())
    )
    return {"threads": [_thread_out(t) for t in rows]}


@router.post("/threads")
def create_thread(
    body: ThreadCreate | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    """Start a new, empty Ask thread."""
    title = (body.title.strip()[:160] if body and body.title and body.title.strip() else "New chat")
    t = AskThread(user_id=user.id, title=title)
    db.add(t)
    db.commit()
    return _thread_out(t)


@router.get("/threads/{thread_id}")
def get_thread(thread_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """A thread with its full message history (rendered identically to when it was created)."""
    t = db.get(AskThread, thread_id)
    if t is None or t.user_id != user.id:
        raise HTTPException(404, "Conversation not found")
    msgs = db.scalars(
        select(AskMessage).where(AskMessage.thread_id == thread_id).order_by(AskMessage.created_at)
    )
    return {
        "id": t.id,
        "title": t.title,
        "messages": [
            {"role": m.role, "content": m.content, "meta": m.meta or {},
             "created_at": m.created_at.isoformat() if m.created_at else ""}
            for m in msgs
        ],
    }


@router.patch("/threads/{thread_id}")
def rename_thread(
    thread_id: str, body: ThreadRename, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    """Rename a thread so it's easy to find later."""
    t = db.get(AskThread, thread_id)
    if t is None or t.user_id != user.id:
        raise HTTPException(404, "Conversation not found")
    title = (body.title or "").strip()[:160]
    if not title:
        raise HTTPException(400, "A title is required")
    t.title = title
    db.add(t)
    db.commit()
    return _thread_out(t)


@router.delete("/threads/{thread_id}")
def delete_thread(thread_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Delete a thread and its messages."""
    t = db.get(AskThread, thread_id)
    if t is None or t.user_id != user.id:
        raise HTTPException(404, "Conversation not found")
    db.execute(delete(AskMessage).where(AskMessage.thread_id == thread_id))
    db.delete(t)
    db.commit()
    return {"ok": True}


def _doc_catalog(db: Session) -> list[dict]:
    docs = db.scalars(select(KnowledgeDoc)).all()
    return [{"id": d.id, "title": d.title, "doc_type": d.doc_type, "url": d.url} for d in docs]


async def _ask_events(db: Session, user: User, body: AskRequest):
    """Ask turn as an event stream, with all its LLM calls bucketed under the "ask" cost line.

    Every call this turn makes (triage + fast polish + deep answer + envelope) is attributed to
    the "ask" call_type via call_type_scope, so Ask spend shows separately from live-meeting spend
    on the /costs dashboard. Both the blocking and SSE endpoints iterate this wrapper, so the scope
    covers the inner generator's calls regardless of how it's consumed."""
    from ..observability.usage import call_type_scope

    with call_type_scope("ask"):
        async for ev in _ask_events_inner(db, user, body):
            yield ev


async def _ask_events_inner(db: Session, user: User, body: AskRequest):
    """Run one Ask turn as an async event stream: 'stage' progress events, then a final 'answer'.

    The blocking endpoint consumes this and returns just the answer; the SSE endpoint forwards
    every event, so the UI shows real progress (which stage, which sources) as it happens.
    """
    query = (body.query or "").strip()
    if not query:
        yield ("answer", {
            "answer": "Ask a question and I'll research it across your connected sources.",
            "evidence": [], "sources": [], "confidence": 0.0, "engine": "none",
            "grounded": False, "persona": "sales", "intent": "general",
            "connected": [], "used": [], "deep_ran": False, "latency_ms": 0,
            "thread_id": body.thread_id, "thread_title": None,
        })
        return

    t0 = time.perf_counter()
    # Same pack the user's meetings use — resolved from their current team (sales↔tech).
    pack = get_pack(pack_for_team(user.team))
    persona = "tech" if pack.manifest.key == "tech" else "sales"
    recent = [ln for ln in (body.context or "").splitlines() if ln.strip()] or None
    yield ("stage", {"stage": "understanding", "label": "Understanding your question"})
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
    inproc_names = await live_sources.available_inprocess(db, user.id)
    yield ("stage", {
        "stage": "searching", "label": "Searching your connected sources",
        "sources": [s.get("name") for s in servers] + inproc_names,
    })

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
        yield ("stage", {
            "stage": "reading", "label": "Reading and cross-checking your sources",
            "sources": [s.get("name") for s in servers] + inproc_names,
        })
        try:
            deep = await pack.deep_answer(
                db=db, meeting=ctx, text=query, intent=intent,
                servers=servers, context=extra_context,
            )
        except Exception as exc:
            log.warning("ask deep_answer failed: %s", exc)

    yield ("stage", {"stage": "composing", "label": "Composing a grounded, cited answer"})

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
    searched = [s.get("name") for s in servers] + (inproc_names if deep else [])
    payload = {
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

    # Persist this turn to the Ask conversation history — create + auto-title the thread if needed.
    thread = db.get(AskThread, body.thread_id) if body.thread_id else None
    if thread is not None and thread.user_id != user.id:
        thread = None  # not the caller's thread — start a fresh one
    if thread is None:
        thread = AskThread(user_id=user.id, title="New chat")
        db.add(thread)
        db.flush()
    if not thread.title or thread.title == "New chat":
        thread.title = (query[:80] + ("…" if len(query) > 80 else "")) or "New chat"
    thread.updated_at = datetime.now(timezone.utc)
    db.add(AskMessage(thread_id=thread.id, role="user", content=query))
    db.add(AskMessage(
        thread_id=thread.id, role="assistant", content=payload["answer"],
        meta={k: v for k, v in payload.items() if k != "answer"},
    ))
    db.add(thread)
    db.commit()
    payload["thread_id"] = thread.id
    payload["thread_title"] = thread.title
    yield ("answer", payload)


@router.post("")
async def ask(
    body: AskRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    """Blocking Ask — same result as the stream, delivered in a single response."""
    result: dict = {}
    async for ev, data in _ask_events(db, user, body):
        if ev == "answer":
            result = data
    return result


@router.post("/stream")
async def ask_stream(
    body: AskRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Server-Sent Events: real per-stage progress (stage + the sources being searched), then
    the final answer. `X-Accel-Buffering: no` tells nginx not to buffer so events arrive live."""
    async def gen():
        try:
            async for ev, data in _ask_events(db, user, body):
                yield f"event: {ev}\ndata: {json.dumps(data)}\n\n"
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("ask stream failed: %s", exc)
            yield f"event: error\ndata: {json.dumps({'message': 'Something went wrong researching that.'})}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
