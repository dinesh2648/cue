"""CRM API — company snapshot + raw objects (incl. AI-created notes/tasks)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..integrations import hubspot
from ..models import CRMObject
from ..schemas import CRMObjectOut

router = APIRouter(prefix="/api/crm", tags=["crm"])


@router.get("/company/{company_id}")
def company(company_id: str, db: Session = Depends(get_db)) -> dict:
    return hubspot.company_context(db, company_id)


@router.get("/objects", response_model=list[CRMObjectOut])
def objects(
    object_type: str | None = Query(None),
    company_id: str | None = Query(None),
    db: Session = Depends(get_db),
) -> list[CRMObject]:
    stmt = select(CRMObject)
    if object_type:
        stmt = stmt.where(CRMObject.object_type == object_type)
    if company_id:
        stmt = stmt.where(CRMObject.company_id == company_id)
    return list(db.scalars(stmt.order_by(CRMObject.created_at.desc())))
