"""Approve-then-act API — list proposed actions, approve (execute), reject."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import capabilities
from ..actions import service
from ..db import get_db
from ..models import Meeting, ProposedAction, User
from ..schemas import ProposedActionOut
from ..security.auth import get_current_user, visible_user_ids

router = APIRouter(prefix="/api", tags=["actions"])


def _check_meeting(db: Session, meeting_id: str, user: User) -> Meeting:
    """Authorize: the meeting must be visible to the caller (RBAC), else 403/404."""
    meeting = db.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(404, "Meeting not found")
    if meeting.owner_user_id in visible_user_ids(db, user) or (
        user.email and user.email in (meeting.attendees or [])
    ):
        return meeting
    raise HTTPException(403, "You don't have access to this meeting")


def _check_action(db: Session, action: ProposedAction, user: User) -> None:
    _check_meeting(db, action.meeting_id, user)


class ProposeRequest(BaseModel):
    action: dict
    pack: str | None = None


class ApproveRequest(BaseModel):
    payload: dict | None = None  # edited fields (e.g. {draft}/{body}/{title}) to apply before executing


@router.get("/meetings/{meeting_id}/actions", response_model=list[ProposedActionOut])
def list_actions(
    meeting_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    _check_meeting(db, meeting_id, user)
    return service.list_for_meeting(db, meeting_id)


@router.post("/meetings/{meeting_id}/actions/propose", response_model=ProposedActionOut)
def propose_action(
    meeting_id: str,
    body: ProposeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    meeting = _check_meeting(db, meeting_id, user)
    return service.propose_from_suggestion_action(
        db, meeting_id=meeting_id, pack=body.pack or meeting.pack, action=body.action
    )


@router.post("/meetings/{meeting_id}/actions/approve-all", response_model=list[ProposedActionOut])
async def approve_all(
    meeting_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    _check_meeting(db, meeting_id, user)
    for a in service.list_for_meeting(db, meeting_id):
        if a.status == "proposed":
            await service.approve(db, a, user.id)
    return service.list_for_meeting(db, meeting_id)


@router.post("/actions/{action_id}/approve", response_model=ProposedActionOut)
async def approve_action(
    action_id: str,
    body: ApproveRequest | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    a = service.get(db, action_id)
    if a is None:
        raise HTTPException(404, "Action not found")
    _check_action(db, a, user)
    if body and body.payload:
        # Apply the rep's edits before executing (approve-then-act with human edit).
        a.payload = {**(a.payload or {}), **body.payload}
        if isinstance(body.payload.get("title"), str) and body.payload["title"].strip():
            a.title = body.payload["title"].strip()[:255]
        db.add(a)
        db.commit()
    return await service.approve(db, a, user.id)


@router.post("/actions/{action_id}/reject", response_model=ProposedActionOut)
def reject_action(
    action_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    a = service.get(db, action_id)
    if a is None:
        raise HTTPException(404, "Action not found")
    _check_action(db, a, user)
    return service.reject(db, a, user.id)


@router.post("/actions/{action_id}/undo", response_model=ProposedActionOut)
async def undo_action(
    action_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    """Reverse an executed write — delete the ticket/note/draft/event, archive the doc."""
    a = service.get(db, action_id)
    if a is None:
        raise HTTPException(404, "Action not found")
    _check_action(db, a, user)
    if not capabilities.enabled(user, "action_undo"):
        raise HTTPException(403, "Undo is turned off in your settings.")
    try:
        return await service.undo(db, a, user.id)
    except Exception as exc:  # provider/network/not-undoable
        raise HTTPException(400, str(exc)[:200]) from exc


@router.get("/me/action-history")
def action_history(
    limit: int = 100, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    """Everything the copilot has written for the meetings this user can see — the audit/history
    view. Executed, failed and undone writes, newest first, with links back to the artifact."""
    vis = visible_user_ids(db, user)
    meetings = {
        m.id: m for m in db.scalars(select(Meeting).where(Meeting.owner_user_id.in_(vis)))
    }
    if not meetings:
        return {"items": []}
    acts = db.scalars(
        select(ProposedAction)
        .where(
            ProposedAction.meeting_id.in_(list(meetings.keys())),
            ProposedAction.status.in_(["executed", "failed", "undone"]),
        )
        .order_by(ProposedAction.decided_at.desc())
        .limit(max(1, min(limit, 500)))
    )
    items = []
    for a in acts:
        m = meetings.get(a.meeting_id)
        res = a.result or {}
        items.append({
            "id": a.id,
            "meeting_id": a.meeting_id,
            "meeting_title": (m.title or m.customer_company or "Meeting") if m else "Meeting",
            "kind": a.kind,
            "title": a.title,
            "status": a.status,
            "result_status": res.get("status", ""),
            "url": res.get("url", "") or "",
            "error": a.error,
            "undoable": a.undoable,
            "decided_at": a.decided_at.isoformat() if a.decided_at else None,
        })
    return {"items": items}


class FeedbackRequest(BaseModel):
    rating: str | None = None       # "up" | "down" | "" (clear)
    correction: str | None = None   # the user's "here's the right answer"


@router.post("/suggestions/{suggestion_id}/feedback")
def suggestion_feedback(
    suggestion_id: str,
    body: FeedbackRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Rate or correct one answer. Corrections steer this user's future answers (feedback loop)."""
    from ..models import Suggestion, SuggestionFeedback

    s = db.get(Suggestion, suggestion_id)
    if s is None:
        raise HTTPException(404, "Answer not found")
    _check_meeting(db, s.meeting_id, user)  # must be able to see the meeting the answer belongs to

    fb = db.scalar(
        select(SuggestionFeedback).where(
            SuggestionFeedback.suggestion_id == suggestion_id,
            SuggestionFeedback.user_id == user.id,
        )
    )
    if fb is None:
        fb = SuggestionFeedback(
            suggestion_id=suggestion_id, user_id=user.id,
            meeting_id=s.meeting_id, query_text=s.query_text or "",
        )
    if body.rating is not None and body.rating in ("up", "down", ""):
        fb.rating = body.rating
    if body.correction is not None:
        fb.correction = body.correction.strip()[:2000]
    db.add(fb)
    db.commit()
    return {"ok": True, "rating": fb.rating, "correction": fb.correction}


@router.get("/jira/projects")
async def jira_projects(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict]:
    """The caller's Jira projects [{key, name}] — powers the project picker on a Jira action."""
    from ..connectors.manager import get_access_token
    from ..integrations import jira

    tok = await get_access_token(db, user.id, "jira")
    if not tok or tok.startswith("demo-"):
        return []
    try:
        return await jira.list_projects(tok)
    except Exception:  # pragma: no cover - provider/network
        return []
