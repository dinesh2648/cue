"""Post-meeting Google Meet recap WITHOUT Recall.

Once a Meet call on the user's calendar has ended, pull the official Meet transcript (Meet REST
API, via the user's Google token + meetings.space.readonly), write it as TranscriptSegment rows,
then run the SAME recap the Recall path runs (`finalize_meeting` → summary, action items,
follow-up email, scorecard). The whole copilot downstream is provider-agnostic — it only needs
segments — so this is an ingestion adapter, not a rewrite.

Gated by settings.meet_transcript_ingest and, per user, by autopilot being ON (the "auto-handle my
meetings" switch) + a connected Google Calendar. There are NO live in-call answers on this path —
the Meet REST API is strictly post-meeting.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .connectors import manager as conn_manager
from .integrations import google_calendar, google_meet
from .meetings_ops import finalize_meeting
from .models import Meeting, TranscriptSegment, User
from .packs.registry import pack_for_team

log = logging.getLogger("copilot.meet_ingest")


def _domain(email: str) -> str:
    return email.split("@", 1)[1].lower() if email and "@" in email else ""


def _role(owner: User, speaker: str) -> str:
    """Map a transcript speaker to rep vs customer. The meeting owner (organizer) is the rep."""
    s = (speaker or "").lower().strip()
    name = (owner.name or "").lower().strip()
    local = (owner.email or "").split("@", 1)[0].lower()
    if s and ((name and (name in s or s in name)) or (local and local in s)):
        return "rep"
    return "customer"


def _epoch(rfc3339: str, fallback: float) -> float:
    try:
        return datetime.fromisoformat((rfc3339 or "").replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return fallback


async def ingest_ended_meet_meetings(db: Session) -> None:
    """One poll pass: recap recently-ended Meet calls that have a ready transcript. Best-effort."""
    if not google_meet.enabled():
        return
    users = list(db.scalars(select(User).where(User.autopilot.is_(True))))
    for user in users:
        token = await conn_manager.get_access_token(db, user.id, "google_calendar")
        if not token or token.startswith("demo-"):
            continue
        try:
            events = await google_calendar.list_recent(
                token, hours=settings.meet_ingest_lookback_hours, max_results=25
            )
        except Exception:  # pragma: no cover - calendar API hiccup; retry next tick
            continue
        for ev in events:
            try:
                await _ingest_one(db, user, token, ev)
            except Exception as exc:  # pragma: no cover - never let one meeting break the pass
                log.warning("meet ingest failed for event %s: %s", ev.get("id"), exc)


async def _ingest_one(db: Session, user: User, token: str, ev: dict) -> None:
    code = google_meet.meeting_code(ev.get("meeting_url", ""))
    if not code:
        return  # not a Google Meet link

    existing = db.scalar(
        select(Meeting).where(Meeting.org_id == user.org_id, Meeting.calendar_event_id == ev["id"])
    )
    # Already recapped, or Recall is handling this one → leave it alone.
    if existing and (existing.status == "ended" or existing.recall_bot_id):
        return

    record = await google_meet.latest_conference_record(token, code)
    if not record or not record.get("name"):
        return  # meeting didn't take place (or hasn't ended) → nothing to recap

    segments = await google_meet.fetch_transcript(token, record["name"])
    if not segments:
        return  # None = transcript not ready / transcription was off; [] = empty → retry later

    meeting = existing or Meeting(
        title=ev.get("title") or "Meeting",
        platform="google_meet",
        customer_contact=next(
            (a for a in ev.get("attendees", []) if _domain(a) and _domain(a) != _domain(user.email)), ""
        ),
        rep_name=user.name or user.email,
        status="scheduled",
        owner_user_id=user.id,
        org_id=user.org_id,
        pack=pack_for_team(user.team),
        meeting_url=ev["meeting_url"],
        calendar_event_id=ev["id"],
        attendees=ev.get("attendees", []),
    )
    if not existing:
        db.add(meeting)
        db.commit()

    # Idempotency: if segments already exist (a prior tick wrote them), just (re)finalize.
    have = db.scalar(select(func.count(TranscriptSegment.id)).where(TranscriptSegment.meeting_id == meeting.id))
    if not have:
        base = _epoch(record.get("startTime", ""), 0.0)
        for i, seg in enumerate(segments):
            db.add(TranscriptSegment(
                meeting_id=meeting.id,
                speaker=(seg["speaker"] or "Speaker")[:120],
                role=_role(user, seg["speaker"]),
                text=seg["text"],
                ts=_epoch(seg.get("start", ""), base + i),
            ))
        db.commit()
        log.info("meet ingest: wrote %d segments for %s (%s)", len(segments), meeting.title, meeting.id)

    await finalize_meeting(db, meeting, with_scorecard=True)
    log.info("meet ingest: recap generated for %s (%s)", meeting.title, meeting.id)
