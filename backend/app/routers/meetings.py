"""Meeting lifecycle API: create → start (live) → transcript/intents/suggestions → end."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..actions import service as action_service
from ..billing import service as billing_service
from ..config import settings
from ..db import get_db
from ..knowledge.store import index
from ..packs.registry import get_pack, pack_for_team
from ..models import (
    AuditLog,
    CRMSyncRecord,
    Intent,
    Meeting,
    MeetingPrep,
    MeetingScorecard,
    MeetingSummary,
    Organization,
    Suggestion,
    TranscriptSegment,
    User,
)
from ..agent import coaching
from ..realtime.engine import is_running, process_utterance, start_meeting
from ..realtime.manager import manager
from ..schemas import (
    CRMSyncOut,
    IntentOut,
    MeetingCreate,
    MeetingOut,
    SegmentOut,
    SuggestionOut,
    SummaryOut,
)
from ..security.auth import get_current_org, get_current_user, visible_user_ids
from ..seed.data import COMPANY_ID

_LIMIT_MSG = "Monthly meeting limit reached for your plan. Upgrade to keep going."

router = APIRouter(prefix="/api/meetings", tags=["meetings"])


class StartRequest(BaseModel):
    scenario: str | None = None


class LiveMeetingRequest(BaseModel):
    # Caps match DB columns so over-long input 422s instead of crashing the insert.
    meeting_url: str = Field(max_length=512)
    title: str = Field("Live customer meeting", max_length=255)
    customer_company: str = Field("", max_length=255)
    customer_contact: str = Field("", max_length=255)
    rep_name: str = Field("", max_length=255)
    crm_company_id: str | None = Field(None, max_length=64)


class UtteranceRequest(BaseModel):
    speaker: str = "Customer"
    role: str = "customer"
    text: str


def _get(db: Session, meeting_id: str) -> Meeting:
    meeting = db.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(404, "Meeting not found")
    return meeting


def _authorized(db: Session, meeting_id: str, user: User) -> Meeting:
    """Fetch a meeting only if the caller may see it (own / report's / org-admin / attendee).

    Prevents IDOR — every per-meeting endpoint must go through this, not `_get`.
    """
    meeting = _get(db, meeting_id)
    if meeting.owner_user_id in visible_user_ids(db, user) or (
        user.email and user.email in (meeting.attendees or [])
    ):
        return meeting
    raise HTTPException(403, "You don't have access to this meeting")


@router.post("", response_model=MeetingOut)
def create_meeting(
    body: MeetingCreate,
    user: User = Depends(get_current_user),
    org: Organization = Depends(get_current_org),
    db: Session = Depends(get_db),
) -> Meeting:
    if not billing_service.within_meeting_limit(db, org):
        raise HTTPException(402, _LIMIT_MSG)
    # Sales-first rollout: only enabled packs are accepted; others fall back to default.
    pack = body.pack if body.pack in settings.enabled_pack_list else "sales"
    meeting = Meeting(
        title=body.title,
        platform=body.platform,
        customer_company=body.customer_company,
        customer_contact=body.customer_contact,
        rep_name=body.rep_name,
        crm_company_id=body.crm_company_id,
        pack=pack,
        owner_user_id=user.id,
        org_id=org.id,
    )
    db.add(meeting)
    db.add(AuditLog(actor=user.id, action="meeting.created", resource=meeting.id))
    db.commit()
    return meeting


@router.post("/demo", response_model=MeetingOut)
def create_demo_meeting(
    user: User = Depends(get_current_user),
    org: Organization = Depends(get_current_org),
    db: Session = Depends(get_db),
) -> Meeting:
    if not billing_service.within_meeting_limit(db, org):
        raise HTTPException(402, _LIMIT_MSG)
    meeting = Meeting(
        title="Northwind Trading — Expansion Call",
        platform="google_meet",
        customer_company="Northwind Trading",
        customer_contact="Sarah Chen",
        rep_name="Alex Rivera",
        crm_company_id=COMPANY_ID,
        owner_user_id=user.id,
        org_id=org.id,
    )
    db.add(meeting)
    db.add(AuditLog(actor=user.id, action="meeting.created.demo", resource=meeting.id))
    db.commit()
    return meeting


@router.post("/live", response_model=MeetingOut)
async def create_live_meeting(
    body: LiveMeetingRequest,
    user: User = Depends(get_current_user),
    org: Organization = Depends(get_current_org),
    db: Session = Depends(get_db),
) -> Meeting:
    """Create a meeting and dispatch a Recall.ai bot into a real Google Meet/Zoom/Teams call."""
    from ..integrations import recall

    if not recall.enabled():
        raise HTTPException(400, "Recall.ai not configured (set RECALL_API_KEY) — use the demo meeting instead.")

    # One copilot per meeting: if a bot is already live on this URL (e.g. dispatched by a
    # colleague), reuse that meeting — add this user as an attendee, no second bot joins.
    existing = db.scalar(
        select(Meeting).where(
            Meeting.org_id == org.id, Meeting.status == "live",
            Meeting.recall_bot_id.is_not(None), Meeting.meeting_url == body.meeting_url,
        ).order_by(Meeting.created_at.desc())
    )
    if existing:
        if user.email and user.email not in (existing.attendees or []):
            existing.attendees = [*(existing.attendees or []), user.email]
            db.commit()
        return existing

    if not billing_service.within_meeting_limit(db, org):
        raise HTTPException(402, _LIMIT_MSG)

    meeting = Meeting(
        title=body.title,
        platform="google_meet",
        customer_company=body.customer_company,
        customer_contact=body.customer_contact,
        rep_name=body.rep_name or user.name,
        crm_company_id=body.crm_company_id,
        owner_user_id=user.id,
        org_id=org.id,
        status="live",
        pack=pack_for_team(user.team),  # Sales vs Tech copilot by the dispatcher's team
        meeting_url=body.meeting_url,
        attendees=[user.email] if user.email else [],
    )
    db.add(meeting)
    db.commit()
    try:
        bot = await recall.create_bot(body.meeting_url, meeting.id)
    except Exception as exc:
        meeting.status = "scheduled"
        db.commit()
        raise HTTPException(502, f"Failed to dispatch meeting bot: {exc}") from exc
    meeting.recall_bot_id = bot.get("id")
    db.add(AuditLog(actor=user.id, action="meeting.bot_dispatched", resource=meeting.id, detail={"bot": bot.get("id")}))
    db.commit()
    return meeting


@router.get("", response_model=list[MeetingOut])
def list_meetings(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[Meeting]:
    from ..security.auth import visible_user_ids

    vis = visible_user_ids(db, user)
    scope = (
        select(Meeting).where(Meeting.org_id == user.org_id)
        if user.org_id else select(Meeting).where(Meeting.owner_user_id == user.id)
    )
    rows = db.scalars(scope.order_by(Meeting.created_at.desc())).all()
    # RBAC: own + (reports' for managers / all for owner-admin) + meetings you attended.
    return [m for m in rows if m.owner_user_id in vis or (user.email and user.email in (m.attendees or []))]


@router.get("/{meeting_id}", response_model=MeetingOut)
def get_meeting(meeting_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Meeting:
    return _authorized(db, meeting_id, user)


@router.post("/{meeting_id}/start")
async def start(
    meeting_id: str, body: StartRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    # Must be async: start_meeting() schedules an asyncio task and so needs the
    # running event loop (a sync handler would run in a threadpool without one).
    _authorized(db, meeting_id, user)
    started = start_meeting(meeting_id, body.scenario)
    return {"started": started, "already_running": not started and is_running(meeting_id)}


@router.post("/{meeting_id}/utterance")
async def utterance(
    meeting_id: str, body: UtteranceRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    _authorized(db, meeting_id, user)
    await process_utterance(meeting_id, body.speaker, body.role, body.text)
    return {"ok": True}


@router.get("/{meeting_id}/transcript", response_model=list[SegmentOut])
def transcript(meeting_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[TranscriptSegment]:
    _authorized(db, meeting_id, user)
    return list(
        db.scalars(
            select(TranscriptSegment)
            .where(TranscriptSegment.meeting_id == meeting_id)
            .order_by(TranscriptSegment.ts)
        )
    )


@router.get("/{meeting_id}/intents", response_model=list[IntentOut])
def intents(meeting_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[Intent]:
    _authorized(db, meeting_id, user)
    return list(
        db.scalars(select(Intent).where(Intent.meeting_id == meeting_id).order_by(Intent.created_at))
    )


@router.get("/{meeting_id}/suggestions", response_model=list[SuggestionOut])
def suggestions(meeting_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[Suggestion]:
    _authorized(db, meeting_id, user)
    return list(
        db.scalars(
            select(Suggestion)
            .where(Suggestion.meeting_id == meeting_id)
            .order_by(Suggestion.created_at)
        )
    )


@router.get("/{meeting_id}/crm-sync", response_model=list[CRMSyncOut])
def crm_sync(meeting_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[CRMSyncRecord]:
    _authorized(db, meeting_id, user)
    return list(
        db.scalars(select(CRMSyncRecord).where(CRMSyncRecord.meeting_id == meeting_id))
    )


def _scorecard_dict(sc: MeetingScorecard) -> dict:
    return {
        "status": "ready",
        "rep_name": sc.rep_name,
        "overall_score": sc.overall_score,
        "headline": sc.headline,
        "dimensions": sc.dimensions,
        "strengths": sc.strengths,
        "improvements": sc.improvements,
        "coaching_tips": sc.coaching_tips,
        "metrics": sc.metrics,
        "created_at": sc.created_at.isoformat() if sc.created_at else None,
    }


@router.get("/{meeting_id}/scorecard")
async def scorecard(
    meeting_id: str, refresh: int = 0, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    """Rep coaching scorecard for this call. Generates + caches on first request."""
    meeting = _authorized(db, meeting_id, user)
    existing = db.scalar(select(MeetingScorecard).where(MeetingScorecard.meeting_id == meeting_id))
    if existing and not refresh:
        return _scorecard_dict(existing)

    segs = list(
        db.scalars(
            select(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id).order_by(TranscriptSegment.ts)
        )
    )
    if not segs:
        return {"status": "no_transcript"}
    transcript = "\n".join(f"{s.speaker}: {s.text}" for s in segs)
    data = await coaching.generate_scorecard(
        {"rep_name": meeting.rep_name, "customer_company": meeting.customer_company, "customer_contact": meeting.customer_contact},
        [{"speaker": s.speaker, "text": s.text, "role": s.role} for s in segs],
        transcript,
    )
    if not data:
        return {"status": "unavailable"}

    sc = existing or MeetingScorecard(meeting_id=meeting_id)
    sc.rep_name = data["rep_name"]
    sc.overall_score = data["overall_score"]
    sc.headline = data["headline"]
    sc.dimensions = data["dimensions"]
    sc.strengths = data["strengths"]
    sc.improvements = data["improvements"]
    sc.coaching_tips = data["coaching_tips"]
    sc.metrics = data["metrics"]
    db.add(sc)
    db.commit()
    return _scorecard_dict(sc)


@router.get("/{meeting_id}/recording")
async def recording(meeting_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Fresh Recall recording link (presigned, short-lived) for this meeting's bot."""
    meeting = _authorized(db, meeting_id, user)
    if not meeting.recall_bot_id:
        return {"status": "no_bot", "url": None}
    from ..integrations import recall

    try:
        return await recall.get_recording_url(meeting.recall_bot_id)
    except Exception as exc:  # pragma: no cover - provider/network
        return {"status": "error", "url": None, "detail": str(exc)[:120]}


@router.get("/{meeting_id}/summary", response_model=SummaryOut)
def get_summary(meeting_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> MeetingSummary:
    _authorized(db, meeting_id, user)
    summary = db.scalar(select(MeetingSummary).where(MeetingSummary.meeting_id == meeting_id))
    if summary is None:
        raise HTTPException(404, "Summary not generated yet")
    return summary


@router.get("/{meeting_id}/prep")
def meeting_prep(meeting_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """The pre-meeting prep brief for this meeting, if one was generated (read-only).

    Prep is keyed by the calendar event; we return the latest brief in this org for that
    event. Returns {found: false} when there's no prep (e.g. an ad-hoc/demo meeting).
    """
    meeting = _authorized(db, meeting_id, user)
    if not meeting.calendar_event_id:
        return {"found": False}
    row = db.scalar(
        select(MeetingPrep)
        .where(
            MeetingPrep.org_id == meeting.org_id,
            MeetingPrep.calendar_event_id == meeting.calendar_event_id,
        )
        .order_by(MeetingPrep.generated_at.desc())
    )
    if row is None:
        return {"found": False}
    return {
        "found": True,
        "title": row.event_title,
        "customer": row.customer,
        "markdown": row.markdown,
        "sources": row.sources or [],
        "engine": row.engine,
        "generated_at": row.generated_at.isoformat() if row.generated_at else None,
    }


@router.post("/{meeting_id}/end", response_model=SummaryOut)
async def end_meeting(meeting_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> MeetingSummary:
    """FR-007: generate summary + automate CRM (notes, tasks, follow-up email draft)."""
    from ..meetings_ops import finalize_meeting

    meeting = _authorized(db, meeting_id, user)
    return await finalize_meeting(db, meeting)
