"""Meeting lifecycle API: create → start (live) → transcript/intents/suggestions → end."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..actions import service as action_service
from ..config import settings
from ..db import get_db
from ..packs.registry import get_pack
from ..integrations import hubspot
from ..models import (
    AuditLog,
    CRMSyncRecord,
    Intent,
    Meeting,
    MeetingSummary,
    Suggestion,
    TranscriptSegment,
    User,
)
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
from ..security.auth import get_current_user
from ..seed.data import COMPANY_ID

router = APIRouter(prefix="/api/meetings", tags=["meetings"])


class StartRequest(BaseModel):
    scenario: str | None = None


class LiveMeetingRequest(BaseModel):
    meeting_url: str
    title: str = "Live customer meeting"
    customer_company: str = ""
    customer_contact: str = ""
    rep_name: str = ""
    crm_company_id: str | None = None


class UtteranceRequest(BaseModel):
    speaker: str = "Customer"
    role: str = "customer"
    text: str


def _get(db: Session, meeting_id: str) -> Meeting:
    meeting = db.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(404, "Meeting not found")
    return meeting


@router.post("", response_model=MeetingOut)
def create_meeting(
    body: MeetingCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Meeting:
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
    )
    db.add(meeting)
    db.add(AuditLog(actor=user.id, action="meeting.created", resource=meeting.id))
    db.commit()
    return meeting


@router.post("/demo", response_model=MeetingOut)
def create_demo_meeting(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Meeting:
    meeting = Meeting(
        title="Northwind Trading — Expansion Call",
        platform="google_meet",
        customer_company="Northwind Trading",
        customer_contact="Sarah Chen",
        rep_name="Alex Rivera",
        crm_company_id=COMPANY_ID,
        owner_user_id=user.id,
    )
    db.add(meeting)
    db.add(AuditLog(actor=user.id, action="meeting.created.demo", resource=meeting.id))
    db.commit()
    return meeting


@router.post("/live", response_model=MeetingOut)
async def create_live_meeting(
    body: LiveMeetingRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Meeting:
    """Create a meeting and dispatch a Recall.ai bot into a real Google Meet/Zoom/Teams call."""
    from ..integrations import recall

    if not recall.enabled():
        raise HTTPException(400, "Recall.ai not configured (set RECALL_API_KEY) — use the demo meeting instead.")

    meeting = Meeting(
        title=body.title,
        platform="google_meet",
        customer_company=body.customer_company,
        customer_contact=body.customer_contact,
        rep_name=body.rep_name or user.name,
        crm_company_id=body.crm_company_id,
        owner_user_id=user.id,
        status="live",
    )
    db.add(meeting)
    db.commit()
    try:
        bot = await recall.create_bot(body.meeting_url, meeting.id)
    except Exception as exc:
        meeting.status = "scheduled"
        db.commit()
        raise HTTPException(502, f"Failed to dispatch meeting bot: {exc}") from exc
    db.add(AuditLog(actor=user.id, action="meeting.bot_dispatched", resource=meeting.id, detail={"bot": bot.get("id")}))
    db.commit()
    return meeting


@router.get("", response_model=list[MeetingOut])
def list_meetings(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[Meeting]:
    return list(
        db.scalars(
            select(Meeting)
            .where(Meeting.owner_user_id == user.id)
            .order_by(Meeting.created_at.desc())
        )
    )


@router.get("/{meeting_id}", response_model=MeetingOut)
def get_meeting(meeting_id: str, db: Session = Depends(get_db)) -> Meeting:
    return _get(db, meeting_id)


@router.post("/{meeting_id}/start")
async def start(meeting_id: str, body: StartRequest, db: Session = Depends(get_db)) -> dict:
    # Must be async: start_meeting() schedules an asyncio task and so needs the
    # running event loop (a sync handler would run in a threadpool without one).
    _get(db, meeting_id)
    started = start_meeting(meeting_id, body.scenario)
    return {"started": started, "already_running": not started and is_running(meeting_id)}


@router.post("/{meeting_id}/utterance")
async def utterance(
    meeting_id: str, body: UtteranceRequest, db: Session = Depends(get_db)
) -> dict:
    _get(db, meeting_id)
    await process_utterance(meeting_id, body.speaker, body.role, body.text)
    return {"ok": True}


@router.get("/{meeting_id}/transcript", response_model=list[SegmentOut])
def transcript(meeting_id: str, db: Session = Depends(get_db)) -> list[TranscriptSegment]:
    return list(
        db.scalars(
            select(TranscriptSegment)
            .where(TranscriptSegment.meeting_id == meeting_id)
            .order_by(TranscriptSegment.ts)
        )
    )


@router.get("/{meeting_id}/intents", response_model=list[IntentOut])
def intents(meeting_id: str, db: Session = Depends(get_db)) -> list[Intent]:
    return list(
        db.scalars(select(Intent).where(Intent.meeting_id == meeting_id).order_by(Intent.created_at))
    )


@router.get("/{meeting_id}/suggestions", response_model=list[SuggestionOut])
def suggestions(meeting_id: str, db: Session = Depends(get_db)) -> list[Suggestion]:
    return list(
        db.scalars(
            select(Suggestion)
            .where(Suggestion.meeting_id == meeting_id)
            .order_by(Suggestion.created_at)
        )
    )


@router.get("/{meeting_id}/crm-sync", response_model=list[CRMSyncOut])
def crm_sync(meeting_id: str, db: Session = Depends(get_db)) -> list[CRMSyncRecord]:
    return list(
        db.scalars(select(CRMSyncRecord).where(CRMSyncRecord.meeting_id == meeting_id))
    )


@router.get("/{meeting_id}/summary", response_model=SummaryOut)
def get_summary(meeting_id: str, db: Session = Depends(get_db)) -> MeetingSummary:
    summary = db.scalar(select(MeetingSummary).where(MeetingSummary.meeting_id == meeting_id))
    if summary is None:
        raise HTTPException(404, "Summary not generated yet")
    return summary


@router.post("/{meeting_id}/end", response_model=SummaryOut)
async def end_meeting(meeting_id: str, db: Session = Depends(get_db)) -> MeetingSummary:
    """FR-007: generate summary + automate CRM (notes, tasks, follow-up email draft)."""
    meeting = _get(db, meeting_id)
    already_ended = meeting.status == "ended"
    meeting.status = "ended"
    meeting.ended_at = meeting.ended_at or datetime.now(timezone.utc)
    db.commit()

    segments = list(
        db.scalars(
            select(TranscriptSegment)
            .where(TranscriptSegment.meeting_id == meeting_id)
            .order_by(TranscriptSegment.ts)
        )
    )
    transcript_text = "\n".join(f"{s.speaker} ({s.role}): {s.text}" for s in segments)
    intent_rows = list(db.scalars(select(Intent).where(Intent.meeting_id == meeting_id)))
    suggestion_rows = list(db.scalars(select(Suggestion).where(Suggestion.meeting_id == meeting_id)))
    crm = hubspot.company_context(db, meeting.crm_company_id)

    summary_data = await get_pack(meeting.pack).summarize(
        meeting={
            "customer_company": meeting.customer_company,
            "customer_contact": meeting.customer_contact,
            "rep_name": meeting.rep_name,
        },
        intents=[{"intent_type": i.intent_type} for i in intent_rows],
        suggestions=[{"actions": s.actions} for s in suggestion_rows],
        crm=crm,
        transcript=transcript_text,
    )

    summary = db.scalar(select(MeetingSummary).where(MeetingSummary.meeting_id == meeting_id))
    if summary is None:
        summary = MeetingSummary(meeting_id=meeting_id)
        db.add(summary)
    summary.executive_summary = summary_data["executive_summary"]
    summary.key_decisions = summary_data["key_decisions"]
    summary.risks = summary_data["risks"]
    summary.action_items = summary_data["action_items"]
    summary.customer_concerns = summary_data["customer_concerns"]
    summary.follow_up_email = summary_data["follow_up_email"]
    db.commit()

    # ── CRM automation (FR-007) — proposed for approval (approve-then-act) ────
    if not already_ended:
        note_body = (
            summary_data["executive_summary"]
            + "\n\nKey decisions:\n- "
            + "\n- ".join(summary_data["key_decisions"])
            + "\n\nRisks:\n- "
            + "\n- ".join(summary_data["risks"])
        )
        action_service.propose(
            db, meeting_id=meeting_id, pack=meeting.pack, action_key="create_note",
            kind="note", title="Log meeting recap note to CRM", payload={"body": note_body},
        )
        for item in summary_data["action_items"][:6]:
            if "recap email" in item.lower():
                continue
            action_service.propose(
                db, meeting_id=meeting_id, pack=meeting.pack, action_key="create_task",
                kind="task", title=item, payload={"title": item},
            )
        action_service.propose(
            db, meeting_id=meeting_id, pack=meeting.pack, action_key="send_email",
            kind="email", title="Send follow-up email to customer",
            payload={"draft": summary_data["follow_up_email"]},
        )
        db.add(AuditLog(actor="copilot", action="meeting.ended", resource=meeting_id))
        db.commit()

    await manager.broadcast(meeting_id, {"type": "summary", "data": summary_data})
    await manager.broadcast(meeting_id, {"type": "status", "data": {"status": "ended"}})
    await manager.broadcast(meeting_id, {"type": "crm_sync", "data": {"synced": True}})
    return summary
