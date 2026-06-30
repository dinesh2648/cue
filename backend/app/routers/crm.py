"""CRM API — company snapshot + raw objects (incl. AI-created notes/tasks)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..integrations import hubspot
from ..models import CRMObject, User
from ..schemas import CRMObjectOut
from ..security.auth import get_current_user

router = APIRouter(prefix="/api/crm", tags=["crm"])


@router.get("/company/{company_id}")
def company(
    company_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    # Tenancy: only expose a company the caller's org owns (CRM objects are org-scoped).
    obj = db.get(CRMObject, company_id)
    if obj is None or (obj.org_id and obj.org_id != user.org_id):
        raise HTTPException(404, "Company not found")
    return hubspot.company_context(db, company_id)


@router.get("/objects", response_model=list[CRMObjectOut])
def objects(
    object_type: str | None = Query(None),
    company_id: str | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[CRMObject]:
    # Tenancy: never return another org's CRM rows.
    stmt = select(CRMObject).where(CRMObject.org_id == user.org_id)
    if object_type:
        stmt = stmt.where(CRMObject.object_type == object_type)
    if company_id:
        stmt = stmt.where(CRMObject.company_id == company_id)
    return list(db.scalars(stmt.order_by(CRMObject.created_at.desc())))
