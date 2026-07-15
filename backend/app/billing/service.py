"""Usage metering, plan-limit enforcement, and Stripe-ready billing (via httpx).

Free plan works with zero config. When STRIPE_SECRET_KEY is set, checkout/portal/webhooks
go live; otherwise upgrades are applied directly (dev mode) so limits are testable.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import ConnectorConnection, Meeting, Organization
from . import plans

log = logging.getLogger("copilot.billing")
_STRIPE = "https://api.stripe.com/v1"


def _month_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def meetings_used(db: Session, org_id: str | None) -> int:
    if not org_id:
        return 0
    return db.scalar(
        select(func.count())
        .select_from(Meeting)
        .where(Meeting.org_id == org_id, Meeting.created_at >= _month_start())
    ) or 0


def connectors_used(db: Session, user_id: str) -> int:
    return db.scalar(
        select(func.count())
        .select_from(ConnectorConnection)
        .where(ConnectorConnection.user_id == user_id, ConnectorConnection.status == "connected")
    ) or 0


def usage(db: Session, org: Organization, user_id: str) -> dict:
    p = plans.plan(org.plan)
    return {
        "plan": org.plan,
        "plan_name": p["name"],
        "meetings_used": meetings_used(db, org.id),
        "meetings_limit": p["meetings_per_month"],
        "connectors_used": connectors_used(db, user_id),
        "connectors_limit": p["max_connectors"],
        "seats": org.seats,
        "features": {"recall": p["recall"], "sso": p["sso"]},
        "billing_enabled": settings.billing_enabled,
    }


def within_meeting_limit(db: Session, org: Organization) -> bool:
    limit = plans.plan(org.plan)["meetings_per_month"]
    return limit is None or meetings_used(db, org.id) < limit


def within_connector_limit(db: Session, user_id: str, org: Organization) -> bool:
    limit = plans.plan(org.plan)["max_connectors"]
    return limit is None or connectors_used(db, user_id) < limit


def backfill_pilot_plan(db: Session) -> int:
    """Pilot mode: put every existing workspace on the Enterprise plan.

    Runs at startup so users who registered before the pilot flag are upgraded too. Idempotent —
    only touches workspaces not already on Enterprise. A no-op when PILOT_MODE is off.
    """
    if not settings.pilot_mode:
        return 0
    orgs = db.scalars(select(Organization).where(Organization.plan != "enterprise")).all()
    for org in orgs:
        org.plan = "enterprise"
    if orgs:
        db.commit()
        log.info("pilot mode: upgraded %d existing workspace(s) to enterprise", len(orgs))
    return len(orgs)


def set_plan(db: Session, org: Organization, plan_key: str, **stripe_ids) -> Organization:
    org.plan = plan_key if plan_key in plans.PLANS else "free"
    if stripe_ids.get("stripe_customer_id"):
        org.stripe_customer_id = stripe_ids["stripe_customer_id"]
    if stripe_ids.get("stripe_subscription_id"):
        org.stripe_subscription_id = stripe_ids["stripe_subscription_id"]
    db.commit()
    return org


# ── Stripe (httpx; no SDK dependency) ─────────────────────────────────────────
async def create_checkout(org: Organization, plan_key: str, email: str, base_url: str) -> str | None:
    """Return a Stripe Checkout URL, or None if Stripe isn't configured (dev mode)."""
    price = plans.stripe_price_id(plan_key)
    if not settings.billing_enabled or not price:
        return None
    data = {
        "mode": "subscription",
        "line_items[0][price]": price,
        "line_items[0][quantity]": "1",
        "success_url": f"{base_url}/settings?upgraded={plan_key}",
        "cancel_url": f"{base_url}/settings",
        "client_reference_id": org.id,
        "metadata[org_id]": org.id,
        "metadata[plan]": plan_key,
        "customer_email": email,
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(
            f"{_STRIPE}/checkout/sessions",
            data=data,
            headers={"Authorization": f"Bearer {settings.stripe_secret_key}"},
        )
        r.raise_for_status()
        return r.json().get("url")


async def create_portal(org: Organization, return_url: str) -> str | None:
    if not settings.billing_enabled or not org.stripe_customer_id:
        return None
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(
            f"{_STRIPE}/billing_portal/sessions",
            data={"customer": org.stripe_customer_id, "return_url": return_url},
            headers={"Authorization": f"Bearer {settings.stripe_secret_key}"},
        )
        r.raise_for_status()
        return r.json().get("url")


def _verify_signature(payload: bytes, sig_header: str) -> bool:
    if not settings.stripe_webhook_secret or not sig_header:
        return False
    parts = dict(p.split("=", 1) for p in sig_header.split(",") if "=" in p)
    t, v1 = parts.get("t"), parts.get("v1")
    if not t or not v1:
        return False
    expected = hmac.new(
        settings.stripe_webhook_secret.encode(), f"{t}.".encode() + payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, v1)


def handle_webhook(db: Session, payload: bytes, sig_header: str) -> bool:
    """Verify a Stripe webhook and apply plan changes. Returns True if handled."""
    if not _verify_signature(payload, sig_header):
        log.warning("stripe webhook signature invalid")
        return False
    try:
        event = json.loads(payload)
    except (ValueError, TypeError):
        log.warning("stripe webhook body was not valid JSON")
        return False
    etype = event.get("type", "")
    obj = event.get("data", {}).get("object", {})
    org_id = (obj.get("metadata") or {}).get("org_id") or obj.get("client_reference_id")

    if etype == "checkout.session.completed" and org_id:
        org = db.get(Organization, org_id)
        if org:
            set_plan(
                db, org, (obj.get("metadata") or {}).get("plan", "pro"),
                stripe_customer_id=obj.get("customer"),
                stripe_subscription_id=obj.get("subscription"),
            )
    elif etype == "customer.subscription.deleted":
        org = db.scalar(select(Organization).where(Organization.stripe_subscription_id == obj.get("id")))
        if org:
            set_plan(db, org, "free")
    return True
