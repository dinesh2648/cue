"""Billing & usage API — plan, usage, upgrade (Stripe checkout / dev upgrade), portal."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..billing import plans, service
from ..config import settings
from ..db import get_db
from ..models import Organization, User
from ..security.auth import get_current_org, get_current_user

router = APIRouter(prefix="/api/billing", tags=["billing"])


class CheckoutRequest(BaseModel):
    plan: str


@router.get("/plans")
def list_plans() -> list[dict]:
    return plans.catalog()


@router.get("")
def get_billing(
    user: User = Depends(get_current_user),
    org: Organization = Depends(get_current_org),
    db: Session = Depends(get_db),
) -> dict:
    return {
        "org": {"id": org.id, "name": org.name, "plan": org.plan, "role": user.role},
        "usage": service.usage(db, org, user.id),
        "plans": plans.catalog(),
    }


@router.post("/checkout")
async def checkout(
    body: CheckoutRequest,
    user: User = Depends(get_current_user),
    org: Organization = Depends(get_current_org),
    db: Session = Depends(get_db),
) -> dict:
    if body.plan not in plans.PLANS or body.plan == "free":
        raise HTTPException(400, "Invalid plan")
    url = await service.create_checkout(org, body.plan, user.email, settings.frontend_url)
    if url:
        return {"url": url, "live": True}
    # Dev mode (no Stripe): apply the upgrade directly so plan limits are testable.
    service.set_plan(db, org, body.plan)
    return {"url": f"{settings.frontend_url}/settings?upgraded={body.plan}", "live": False}


@router.post("/portal")
async def portal(
    org: Organization = Depends(get_current_org), db: Session = Depends(get_db)
) -> dict:
    url = await service.create_portal(org, f"{settings.frontend_url}/settings")
    if not url:
        raise HTTPException(400, "Billing portal unavailable (Stripe not configured or no subscription)")
    return {"url": url}
