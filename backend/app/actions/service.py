"""Approve-then-act: propose write actions, approve to execute, reject to discard.

Reads run freely; writes land as `proposed` ProposedActions until a human approves, then
execute via the connector layer and are audited. Packs reuse this for any write (Sales
CRM notes/tasks/email today; Developer Jira/PR later).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..integrations import hubspot
from ..models import AuditLog, CRMSyncRecord, Meeting, ProposedAction

log = logging.getLogger("copilot.actions")

# suggestion-action `type` → (kind, is_write)
_TYPE_MAP: dict[str, tuple[str, bool]] = {
    "share_document": ("document", True),
    "create_task": ("task", True),
    "start_workflow": ("workflow", True),
    "schedule_followup": ("task", True),
    "send_email": ("email", True),
    "escalate": ("task", True),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def list_for_meeting(db: Session, meeting_id: str) -> list[ProposedAction]:
    return list(
        db.scalars(
            select(ProposedAction)
            .where(ProposedAction.meeting_id == meeting_id)
            .order_by(ProposedAction.created_at)
        )
    )


def get(db: Session, action_id: str) -> ProposedAction | None:
    return db.get(ProposedAction, action_id)


def propose(
    db: Session,
    *,
    meeting_id: str,
    pack: str,
    action_key: str,
    kind: str,
    title: str,
    payload: dict,
    write: bool = True,
    autonomy: str = "approve",
) -> ProposedAction:
    pa = ProposedAction(
        meeting_id=meeting_id,
        pack=pack,
        action_key=action_key,
        kind=kind,
        title=title,
        payload=payload or {},
        write=write,
        autonomy=autonomy,
        status="proposed",
    )
    db.add(pa)
    db.commit()
    if autonomy == "auto":  # opt-in autonomous mode executes immediately
        approve(db, pa, approver="auto")
    return pa


def propose_from_suggestion_action(
    db: Session, *, meeting_id: str, pack: str, action: dict
) -> ProposedAction:
    atype = action.get("type", "action")
    kind, write = _TYPE_MAP.get(atype, ("task", True))
    return propose(
        db,
        meeting_id=meeting_id,
        pack=pack,
        action_key=atype,
        kind=kind,
        title=action.get("label", atype),
        payload=action,
        write=write,
    )


def approve(db: Session, action: ProposedAction, approver: str) -> ProposedAction:
    if action.status != "proposed":
        return action
    try:
        action.result = _execute(db, action)
        action.status = "executed"
        action.error = None
    except Exception as exc:  # pragma: no cover - execution failure path
        action.status = "failed"
        action.error = str(exc)
        log.warning("action execute failed key=%s: %s", action.action_key, exc)
    action.approver = approver
    action.decided_at = _now()
    db.add(
        AuditLog(
            actor=approver,
            action=f"action.{action.status}",
            resource=action.meeting_id,
            detail={"key": action.action_key, "kind": action.kind},
        )
    )
    db.commit()
    return action


def reject(db: Session, action: ProposedAction, approver: str) -> ProposedAction:
    if action.status == "proposed":
        action.status = "rejected"
        action.approver = approver
        action.decided_at = _now()
        db.add(AuditLog(actor=approver, action="action.rejected", resource=action.meeting_id))
        db.commit()
    return action


def _execute(db: Session, action: ProposedAction) -> dict:
    """Perform the write via the connector layer (mock CRM by default)."""
    meeting = db.get(Meeting, action.meeting_id)
    cid = meeting.crm_company_id if meeting else None
    p = action.payload or {}
    kind = action.kind

    if kind == "note":
        rec = hubspot.create_note(db, action.meeting_id, cid, p.get("body") or action.title)
        return {"type": "note", "crm_id": rec.external_id}
    if kind == "task":
        rec = hubspot.create_task(db, action.meeting_id, cid, p.get("title") or action.title, p.get("notes", ""))
        return {"type": "task", "crm_id": rec.external_id}
    if kind == "email":
        rec = hubspot.save_email_draft(db, action.meeting_id, cid, p.get("draft") or p.get("body") or action.title)
        return {"type": "email", "crm_id": rec.id}

    # document share / workflow / fallback — record the activity
    rec = CRMSyncRecord(meeting_id=action.meeting_id, object_type=kind, payload=p, status="created")
    db.add(rec)
    db.commit()
    return {"type": kind, "crm_id": rec.id, "url": p.get("url", "")}
