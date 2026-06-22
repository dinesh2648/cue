"""Inbound webhooks (Recall.ai meeting-bot transcript stream)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Query, Request
from sqlalchemy.orm import Session

from ..billing import service as billing_service
from ..db import SessionLocal
from ..integrations import recall
from ..models import Meeting
from ..realtime.engine import process_utterance

log = logging.getLogger("copilot.webhooks")
router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


def _role(meeting: Meeting | None, speaker: str, is_host: bool) -> str:
    """Map a meeting participant to rep vs customer."""
    if is_host:
        return "rep"
    if meeting and meeting.rep_name and speaker:
        if speaker.lower().strip() in meeting.rep_name.lower() or meeting.rep_name.lower() in speaker.lower():
            return "rep"
    return "customer"


@router.post("/recall")
async def recall_webhook(request: Request, meeting_id: str = Query(...)) -> dict:
    body = await request.json()
    seg = recall.parse_transcript_event(body)
    if not seg:
        return {"ok": True, "skipped": True}

    db: Session = SessionLocal()
    try:
        meeting = db.get(Meeting, meeting_id)
        role = _role(meeting, seg["speaker"], seg["is_host"])
    finally:
        db.close()

    await process_utterance(meeting_id, seg["speaker"], role, seg["text"])
    return {"ok": True}


@router.post("/stripe")
async def stripe_webhook(request: Request) -> dict:
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    db: Session = SessionLocal()
    try:
        handled = billing_service.handle_webhook(db, payload, sig)
    finally:
        db.close()
    return {"ok": handled}
