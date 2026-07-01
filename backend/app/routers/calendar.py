"""Calendar — the signed-in user's upcoming meetings from their connected Google Calendar.

Reads the user's own events with their OAuth token (per-user scope). Returns a structured
result that always tells the UI *why* there's nothing to show (not connected, API not
enabled, etc.) instead of failing silently.
"""
from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import prep_ops
from ..connectors import manager
from ..db import get_db
from ..integrations import google_calendar
from ..models import User
from ..security.auth import get_current_user

log = logging.getLogger("copilot.calendar")
router = APIRouter(prefix="/api/calendar", tags=["calendar"])


async def _find_event(db: Session, user: User, event_id: str) -> dict:
    """Locate one of the user's own upcoming events by id (their calendar, their token)."""
    token = await manager.get_access_token(db, user.id, "google_calendar")
    if not token or token.startswith("demo-"):
        raise HTTPException(400, "Connect Google Calendar with your real Google account first")
    try:
        events = await google_calendar.list_upcoming(token)
    except Exception as exc:  # pragma: no cover - network/parse
        raise HTTPException(502, f"Could not read your calendar: {str(exc)[:120]}")
    event = next((e for e in events if e.get("id") == event_id), None)
    if event is None:
        raise HTTPException(404, "Event not found on your upcoming calendar")
    return event


def _prep_out(row) -> dict:
    return {
        "event_id": row.calendar_event_id,
        "title": row.event_title,
        "customer": row.customer,
        "markdown": row.markdown,
        "sources": row.sources or [],
        "engine": row.engine,
        "generated_at": row.generated_at.isoformat() if row.generated_at else None,
    }


@router.get("/upcoming")
async def upcoming(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    conn = manager.get_connection(db, user.id, "google_calendar")
    if conn is None or conn.status != "connected":
        return {"connected": False, "events": [], "error": "not_connected"}

    token = await manager.get_access_token(db, user.id, "google_calendar")
    if not token:
        return {"connected": True, "events": [], "error": "token_unavailable"}

    # Demo connections store a placeholder token (no real Google account behind it).
    if token.startswith("demo-"):
        return {"connected": True, "events": [], "error": "demo_connection"}

    try:
        events = await google_calendar.list_upcoming(token)
        return {"connected": True, "events": events, "error": None}
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        detail = ""
        try:
            detail = (exc.response.json().get("error", {}) or {}).get("message", "")
        except Exception:  # pragma: no cover
            pass
        low = detail.lower()
        if code == 403 and ("has not been used" in low or "is disabled" in low or "accessnotconfigured" in low):
            error = "api_disabled"
        elif code in (401, 403):
            error = "permission"
        else:
            error = f"http_{code}"
        log.warning("calendar fetch failed %s: %s", code, detail)
        return {"connected": True, "events": [], "error": error, "detail": detail[:240]}
    except Exception as exc:  # pragma: no cover - network/parse
        log.warning("calendar fetch error: %s", exc)
        return {"connected": True, "events": [], "error": "fetch_failed"}


@router.get("/prep/{event_id}")
async def get_prep(
    event_id: str,
    refresh: int = 0,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Preparation brief for an upcoming meeting — cached, or researched on demand.

    Researches the rep's connected sources (HubSpot/Notion/Drive/Gmail) + prior meeting
    notes + web. `refresh=1` regenerates. Returns the cached one immediately if fresh.
    """
    if not refresh:
        cached = prep_ops.get_cached(db, user, event_id)
        if cached and prep_ops._usable(cached, user):  # fresh AND matches current persona
            return {**_prep_out(cached), "cached": True}
    event = await _find_event(db, user, event_id)
    row = await prep_ops.build_prep(db, user, event, force=bool(refresh))
    return {**_prep_out(row), "cached": False}
