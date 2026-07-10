"""Public shareable links for meeting artifacts.

Create/list/revoke require an authorized org user (owner/manager/admin scope). Reading a link is
PUBLIC — the unguessable token is the access control, and only the artifacts the creator chose
(`scopes`) are ever returned. Links are revocable and can carry an expiry.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import (
    Meeting,
    MeetingPrep,
    MeetingSummary,
    ShareLink,
    TranscriptSegment,
    User,
)
from ..security.auth import get_current_user, visible_user_ids

log = logging.getLogger("copilot.share")
router = APIRouter(prefix="/api", tags=["share"])

_ALLOWED = {"prep", "transcript", "recording", "summary"}


def _norm_scopes(scopes: list[str] | None) -> list[str]:
    out: set[str] = set()
    for x in scopes or []:
        v = str(x).lower().strip()
        if v == "all":
            out |= _ALLOWED
        elif v in _ALLOWED:
            out.add(v)
    return sorted(out or _ALLOWED)  # empty selection => share everything ("all together")


def _can_manage(db: Session, meeting: Meeting, user: User) -> bool:
    # Owner / their manager / an org admin — not arbitrary attendees (public links are sensitive).
    return meeting.owner_user_id in visible_user_ids(db, user)


def _public_url(token: str) -> str:
    return f"{settings.frontend_url.rstrip('/')}/share/{token}"


def _link_payload(link: ShareLink) -> dict:
    return {
        "token": link.token,
        "url": _public_url(link.token),
        "scopes": link.scopes or [],
        "expires_at": link.expires_at.isoformat() if link.expires_at else None,
        "revoked": link.revoked,
        "view_count": link.view_count,
        "created_at": link.created_at.isoformat() if link.created_at else None,
    }


class ShareCreate(BaseModel):
    scopes: list[str] = []            # any of prep|transcript|recording|summary, or ["all"]
    expires_days: int | None = None   # None = never expires


@router.post("/meetings/{meeting_id}/share")
def create_share(
    meeting_id: str, body: ShareCreate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
) -> dict:
    meeting = db.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(404, "Meeting not found")
    if not _can_manage(db, meeting, user):
        raise HTTPException(403, "You can't create share links for this meeting.")
    expires_at = None
    if body.expires_days and body.expires_days > 0:
        from datetime import datetime, timezone
        expires_at = datetime.now(timezone.utc) + timedelta(days=min(body.expires_days, 365))
    link = ShareLink(
        meeting_id=meeting_id, org_id=meeting.org_id, created_by=user.id,
        scopes=_norm_scopes(body.scopes), expires_at=expires_at,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    log.info("share link created meeting=%s scopes=%s by=%s", meeting_id, link.scopes, user.id)
    return _link_payload(link)


@router.get("/meetings/{meeting_id}/shares")
def list_shares(
    meeting_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user),
) -> list[dict]:
    meeting = db.get(Meeting, meeting_id)
    if meeting is None or not _can_manage(db, meeting, user):
        raise HTTPException(403, "Not authorized")
    rows = db.scalars(
        select(ShareLink).where(ShareLink.meeting_id == meeting_id).order_by(ShareLink.created_at.desc())
    )
    return [_link_payload(x) for x in rows]


@router.post("/share/{token}/revoke")
def revoke_share(
    token: str, db: Session = Depends(get_db), user: User = Depends(get_current_user),
) -> dict:
    link = db.scalar(select(ShareLink).where(ShareLink.token == token))
    if link is None:
        raise HTTPException(404, "Link not found")
    meeting = db.get(Meeting, link.meeting_id)
    if meeting is None or not _can_manage(db, meeting, user):
        raise HTTPException(403, "Not authorized")
    link.revoked = True
    db.add(link)
    db.commit()
    return {"revoked": True, "token": token}


# ── PUBLIC (no auth) ──────────────────────────────────────────────────────────
async def _build_bundle(db: Session, meeting: Meeting, scopes: list[str]) -> dict:
    bundle: dict = {
        "meeting": {
            "title": meeting.title,
            "customer_company": meeting.customer_company,
            "date": meeting.created_at.isoformat() if meeting.created_at else None,
            "status": meeting.status,
        },
        "scopes": scopes,
    }
    if "summary" in scopes:
        s = db.scalar(select(MeetingSummary).where(MeetingSummary.meeting_id == meeting.id))
        bundle["summary"] = None if s is None else {
            "executive_summary": s.executive_summary,
            "key_decisions": s.key_decisions or [],
            "risks": s.risks or [],
            "action_items": s.action_items or [],
            "customer_concerns": s.customer_concerns or [],
            "follow_up_email": s.follow_up_email or "",
        }
    if "prep" in scopes:
        row = None
        if meeting.calendar_event_id:
            row = db.scalar(
                select(MeetingPrep)
                .where(MeetingPrep.org_id == meeting.org_id,
                       MeetingPrep.calendar_event_id == meeting.calendar_event_id)
                .order_by(MeetingPrep.generated_at.desc())
            )
        bundle["prep"] = None if row is None else {
            "title": row.event_title, "markdown": row.markdown, "sources": row.sources or [],
        }
    if "transcript" in scopes:
        segs = db.scalars(
            select(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting.id)
            .order_by(TranscriptSegment.ts)
        )
        bundle["transcript"] = [{"speaker": s.speaker, "role": s.role, "text": s.text} for s in segs]
    if "recording" in scopes:
        rec = {"status": "no_bot", "url": None}
        if meeting.recall_bot_id:
            from ..integrations import recall
            try:
                rec = await recall.get_recording_url(meeting.recall_bot_id)
            except Exception as exc:  # pragma: no cover - provider/network
                rec = {"status": "error", "url": None, "detail": str(exc)[:120]}
        bundle["recording"] = rec
    return bundle


@router.get("/share/{token}")
async def read_share(token: str, db: Session = Depends(get_db)) -> dict:
    """PUBLIC — anyone with the link. Returns only the scoped artifacts; 404 if invalid/revoked/expired."""
    from datetime import datetime, timezone

    link = db.scalar(select(ShareLink).where(ShareLink.token == token))
    if link is None or link.revoked:
        raise HTTPException(404, "This share link is not available.")
    if link.expires_at:
        exp = link.expires_at if link.expires_at.tzinfo else link.expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > exp:
            raise HTTPException(410, "This share link has expired.")
    meeting = db.get(Meeting, link.meeting_id)
    if meeting is None:
        raise HTTPException(404, "This share link is not available.")
    link.view_count = (link.view_count or 0) + 1
    db.add(link)
    db.commit()
    return await _build_bundle(db, meeting, _norm_scopes(link.scopes))
