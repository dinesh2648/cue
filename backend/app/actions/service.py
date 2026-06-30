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
    # The title column is varchar(255); keep the full text in the payload and store a
    # display-safe title (LLM-generated next steps can run long).
    display_title = title or ""
    if len(display_title) > 255:
        display_title = display_title[:252].rstrip() + "…"
    pa = ProposedAction(
        meeting_id=meeting_id,
        pack=pack,
        action_key=action_key,
        kind=kind,
        title=display_title,
        payload=payload or {},
        write=write,
        autonomy=autonomy,
        status="proposed",
    )
    db.add(pa)
    db.commit()
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


async def approve(db: Session, action: ProposedAction, approver: str) -> ProposedAction:
    if action.status != "proposed":
        return action
    try:
        action.result = await _execute(db, action)
        action.status = "executed"
        action.error = None
    except Exception as exc:  # pragma: no cover - execution failure path
        action.status = "failed"
        action.error = str(exc)[:500]
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


def _record(db: Session, meeting_id: str, kind: str, payload: dict, status: str) -> CRMSyncRecord:
    rec = CRMSyncRecord(meeting_id=meeting_id, object_type=kind, payload=payload, status=status)
    db.add(rec)
    db.commit()
    return rec


async def _token(db: Session, owner: str | None, provider: str) -> str | None:
    if not owner:
        return None
    from ..connectors import manager

    tok = await manager.get_access_token(db, owner, provider)
    return None if (not tok or tok.startswith("demo-")) else tok


async def _execute(db: Session, action: ProposedAction) -> dict:
    """Perform the write — real connector if available, else record a draft (approve-then-act)."""
    meeting = db.get(Meeting, action.meeting_id)
    owner = meeting.owner_user_id if meeting else None
    cid = meeting.crm_company_id if meeting else None
    p = action.payload or {}
    kind = action.kind

    # ── Agentic connector writes (real, as the meeting owner) ────────────────
    if kind == "notion_doc":
        from ..integrations import notion

        token = await _token(db, owner, "notion")
        if token:
            res = await notion.create_page(token, p.get("title") or action.title, p.get("body") or "")
            return {"type": "notion_doc", "url": res.get("url"), "page_id": res.get("id")}
        rec = _record(db, action.meeting_id, kind, p, "drafted")
        return {"type": "notion_doc", "crm_id": rec.id, "status": "drafted — connect Notion (write) to auto-create"}

    if kind == "reminder":
        from ..integrations import google_calendar

        token = await _token(db, owner, "google_calendar")
        if token:
            res = await google_calendar.create_event(token, p.get("title") or action.title, p.get("detail", ""))
            return {"type": "reminder", "url": res.get("url")}
        rec = _record(db, action.meeting_id, kind, p, "pending")
        return {"type": "reminder", "crm_id": rec.id, "status": "connect Google Calendar to schedule"}

    if kind == "jira_ticket":
        from ..integrations import jira

        token = await _token(db, owner, "jira")
        if token:
            res = await jira.create_issue(token, p.get("summary") or action.title, p.get("description", ""))
            return {"type": "jira_ticket", "key": res.get("key"), "url": res.get("url")}
        rec = _record(db, action.meeting_id, kind, p, "pending")
        return {"type": "jira_ticket", "crm_id": rec.id, "status": "connect Jira to auto-create the ticket"}

    # ── CRM writes (mock CRM layer) ──────────────────────────────────────────
    if kind == "note":
        rec = hubspot.create_note(db, action.meeting_id, cid, p.get("body") or action.title)
        return {"type": "note", "crm_id": rec.external_id}
    if kind == "task":
        rec = hubspot.create_task(db, action.meeting_id, cid, p.get("title") or action.title, p.get("notes", ""))
        return {"type": "task", "crm_id": rec.external_id}
    if kind == "email":
        rec = hubspot.save_email_draft(db, action.meeting_id, cid, p.get("draft") or p.get("body") or action.title)
        return {"type": "email", "crm_id": rec.id}

    rec = _record(db, action.meeting_id, kind, p, "created")
    return {"type": kind, "crm_id": rec.id, "url": p.get("url", "")}
