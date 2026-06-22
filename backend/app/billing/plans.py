"""Plan catalog. Limits are config-driven — tune freely.

`meetings_per_month=None` and `max_connectors=None` mean unlimited.
"""
from __future__ import annotations

from ..config import settings

PLANS: dict[str, dict] = {
    "free": {
        "key": "free",
        "name": "Free",
        "price_monthly": 0,
        "meetings_per_month": 5,
        "max_connectors": 2,
        "seats": 1,
        "recall": False,
        "sso": False,
        "blurb": "Try the copilot on a handful of meetings.",
        "stripe_price_attr": None,
    },
    "pro": {
        "key": "pro",
        "name": "Pro",
        "price_monthly": 49,
        "meetings_per_month": None,
        "max_connectors": None,
        "seats": None,
        "recall": True,
        "sso": False,
        "blurb": "Unlimited meetings, all connectors, real meeting bots.",
        "stripe_price_attr": "stripe_price_pro",
    },
    "enterprise": {
        "key": "enterprise",
        "name": "Enterprise",
        "price_monthly": None,  # custom / contact sales
        "meetings_per_month": None,
        "max_connectors": None,
        "seats": None,
        "recall": True,
        "sso": True,
        "blurb": "SSO, custom limits, security review, priority support.",
        "stripe_price_attr": "stripe_price_enterprise",
    },
}

ORDER = ["free", "pro", "enterprise"]


def plan(key: str | None) -> dict:
    return PLANS.get(key or "free", PLANS["free"])


def stripe_price_id(key: str) -> str | None:
    attr = plan(key).get("stripe_price_attr")
    return getattr(settings, attr) if attr else None


def catalog() -> list[dict]:
    return [PLANS[k] for k in ORDER]
