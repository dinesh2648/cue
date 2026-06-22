"""Approve-then-act API — list proposed actions, approve (execute), reject."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..actions import service
from ..db import get_db
from ..models import Meeting, User
from ..schemas import ProposedActionOut
from ..security.auth import get_current_user

router = APIRouter(prefix="/api", tags=["actions"])


class ProposeRequest(BaseModel):
    action: dict
    pack: str | None = None


@router.get("/meetings/{meeting_id}/actions", response_model=list[ProposedActionOut])
def list_actions(
    meeting_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    return service.list_for_meeting(db, meeting_id)


@router.post("/meetings/{meeting_id}/actions/propose", response_model=ProposedActionOut)
def propose_action(
    meeting_id: str,
    body: ProposeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    meeting = db.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(404, "Meeting not found")
    return service.propose_from_suggestion_action(
        db, meeting_id=meeting_id, pack=body.pack or meeting.pack, action=body.action
    )


@router.post("/meetings/{meeting_id}/actions/approve-all", response_model=list[ProposedActionOut])
def approve_all(
    meeting_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    for a in service.list_for_meeting(db, meeting_id):
        if a.status == "proposed":
            service.approve(db, a, user.id)
    return service.list_for_meeting(db, meeting_id)


@router.post("/actions/{action_id}/approve", response_model=ProposedActionOut)
def approve_action(
    action_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    a = service.get(db, action_id)
    if a is None:
        raise HTTPException(404, "Action not found")
    return service.approve(db, a, user.id)


@router.post("/actions/{action_id}/reject", response_model=ProposedActionOut)
def reject_action(
    action_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    a = service.get(db, action_id)
    if a is None:
        raise HTTPException(404, "Action not found")
    return service.reject(db, a, user.id)
