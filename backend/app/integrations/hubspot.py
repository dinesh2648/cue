"""CRM data layer (HubSpot-shaped).

`company_context` is the structured snapshot the copilot reads (seeded `CRMObject`
table by default; per-user HubSpot via the MCP connectors in production). Post-meeting
automation writes the recap note / tasks / email draft into the local CRM store and
records them in `CRMSyncRecord`. Real per-user write-back (via the employee's own
HubSpot MCP connection) is the next step — the local store keeps the demo self-contained.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import CRMObject, CRMSyncRecord

log = logging.getLogger("copilot.hubspot")


def _objects(db: Session, object_type: str, company_id: str | None = None) -> list[CRMObject]:
    stmt = select(CRMObject).where(CRMObject.object_type == object_type)
    if company_id is not None:
        stmt = stmt.where(CRMObject.company_id == company_id)
    return list(db.scalars(stmt))


def company_context(db: Session, company_id: str | None) -> dict:
    """Structured CRM snapshot the agent retrieves from (the FR-004 HubSpot side)."""
    if not company_id:
        return {}
    company = db.get(CRMObject, company_id)
    deals = _objects(db, "deal", company_id)
    tickets = _objects(db, "ticket", company_id)
    contacts = _objects(db, "contact", company_id)
    tasks = _objects(db, "task", company_id)

    open_tickets = [t for t in tickets if t.properties.get("status", "").lower() != "closed"]
    return {
        "company": company.properties if company else {},
        "deals": [d.properties for d in deals],
        "tickets": [t.properties for t in tickets],
        "open_ticket_count": len(open_tickets),
        "contacts": [c.properties for c in contacts],
        "tasks": [t.properties for t in tasks],
    }


def _record_sync(
    db: Session, meeting_id: str, object_type: str, payload: dict, external_id: str | None
) -> CRMSyncRecord:
    rec = CRMSyncRecord(
        meeting_id=meeting_id,
        object_type=object_type,
        payload=payload,
        external_id=external_id,
        status="created",
    )
    db.add(rec)
    return rec


def _meeting_org(db: Session, meeting_id: str) -> str | None:
    """Tenant that owns a CRM write — derived from the meeting so reads stay org-scoped."""
    from ..models import Meeting

    m = db.get(Meeting, meeting_id)
    return m.org_id if m else None


def create_note(db: Session, meeting_id: str, company_id: str | None, body: str) -> CRMSyncRecord:
    obj = CRMObject(
        object_type="note",
        company_id=company_id,
        org_id=_meeting_org(db, meeting_id),
        properties={"body": body, "source": "ai_copilot"},
        source="mock",
    )
    db.add(obj)
    db.flush()
    rec = _record_sync(db, meeting_id, "note", {"body": body}, obj.id)
    db.commit()
    return rec


def create_task(
    db: Session, meeting_id: str, company_id: str | None, title: str, notes: str = ""
) -> CRMSyncRecord:
    obj = CRMObject(
        object_type="task",
        company_id=company_id,
        org_id=_meeting_org(db, meeting_id),
        properties={"title": title, "notes": notes, "status": "NOT_STARTED"},
        source="mock",
    )
    db.add(obj)
    db.flush()
    rec = _record_sync(db, meeting_id, "task", {"title": title, "notes": notes}, obj.id)
    db.commit()
    return rec


def save_email_draft(db: Session, meeting_id: str, company_id: str | None, draft: str) -> CRMSyncRecord:
    rec = _record_sync(db, meeting_id, "email_draft", {"draft": draft}, None)
    db.commit()
    return rec
