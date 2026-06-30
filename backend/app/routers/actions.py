"""Approve-then-act API — list proposed actions, approve (execute), reject."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

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
