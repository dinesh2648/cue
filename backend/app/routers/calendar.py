"""Calendar — the signed-in user's upcoming meetings from their connected Google Calendar.

Reads the user's own events with their OAuth token (per-user scope). Returns a structured
result that always tells the UI *why* there's nothing to show (not connected, API not
enabled, etc.) instead of failing silently.
"""
from __future__ import annotations

import asyncio
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import prep_ops
from ..connectors import manager
from ..db import SessionLocal, get_db
from ..integrations import google_calendar
from ..models import User
from ..security.auth import get_current_user

log = logging.getLogger("copilot.calendar")
router = APIRouter(prefix="/api/calendar", tags=["calendar"])


async def _find_event(db: Session, user: User, event_id: str) -> dict:
    """Locate one of the user's own events by id (their calendar, their token).

    Fetches the event DIRECTLY by id (authoritative, no time-window limit) — a list scan misses
    anything past the page/window, which is what made prep 404 for meetings further out. Falls
    back to scanning the upcoming list only if the direct lookup can't resolve it.
    """
    token = await manager.get_access_token(db, user.id, "google_calendar")
    if not token or token.startswith("demo-"):
        raise HTTPException(400, "Connect Google Calendar with your real Google account first")
    try:
        event = await google_calendar.get_event(token, event_id)
        if event is None:  # not resolvable by id → fall back to a wide upcoming scan
            events = await google_calendar.list_upcoming(token, max_results=250, days=120)
            event = next((e for e in events if e.get("id") == event_id), None)
    except Exception as exc:  # pragma: no cover - network/parse
        raise HTTPException(502, f"Could not read your calendar: {str(exc)[:120]}")
    if event is None:
        raise HTTPException(404, "That meeting isn't on your Google Calendar — reload the calendar and try again")
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
async def upcoming(
    days: int = 30, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    days = max(1, min(days, 90))  # range window the UI can pick (7 / 30 / 90)
    conn = manager.get_connection(db, user.id, "google_calendar")
    if conn is None or conn.status != "connected":
        return {"connected": False, "events": [], "error": "not_connected", "days": days}

    token = await manager.get_access_token(db, user.id, "google_calendar")
    if not token:
        return {"connected": True, "events": [], "error": "token_unavailable", "days": days}

    # Demo connections store a placeholder token (no real Google account behind it).
    if token.startswith("demo-"):
        return {"connected": True, "events": [], "error": "demo_connection", "days": days}

    try:
        events = await google_calendar.list_upcoming(token, max_results=50, days=days)
        return {"connected": True, "events": events, "error": None, "days": days}
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


# Live research (Jira/GitHub/Notion + Gmail bodies + LLM) can take 60–90s — too long to hold an
# HTTP request open (nginx 504). So generation runs in the background and the client polls.
# Two-phase: a fast compose brief lands first (client shows it), then the richer researched brief
# replaces it. `_prep_inflight` = phase 1 (nothing to show yet); `_prep_refining` = phase 2 (a
# quick brief is cached and being upgraded).
_prep_inflight: set[str] = set()
_prep_refining: set[str] = set()
_prep_error: dict[str, str] = {}
_prep_tasks: set = set()  # hold task refs so they aren't garbage-collected mid-run


async def _generate_prep_bg(user_id: str, event: dict) -> None:
    key = f"{user_id}:{event['id']}"
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if not user:
            return
        # Phase 1 — fast compose brief so the client sees content within seconds.
        _, bundle = await prep_ops.build_prep_quick(db, user, event)
        _prep_error.pop(key, None)
        _prep_inflight.discard(key)   # quick brief is cached — the client can fetch it now…
        _prep_refining.add(key)       # …while we research the richer version
        # Phase 2 — deep research; upgrade the cached brief in place if it comes back richer.
        try:
            await prep_ops.build_prep_refine(db, user, event, bundle)
        except Exception as exc:  # research failed — the fast brief already stands
            log.warning("prep refine failed for %s: %s", key, exc)
    except Exception as exc:  # pragma: no cover - surfaced to the client on the next poll
        _prep_error[key] = str(exc)[:200]
        log.warning("background prep failed for %s: %s", key, exc)
    finally:
        db.close()
        _prep_inflight.discard(key)
        _prep_refining.discard(key)


@router.get("/prep/{event_id}")
async def get_prep(
    event_id: str,
    refresh: int = 0,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Preparation brief for an upcoming meeting. Returns the cached brief immediately if fresh;
    otherwise kicks off background research and returns {generating: true} so the client polls.
    `refresh=1` forces a rebuild. Researches connected sources (Jira/GitHub/HubSpot/Notion +
    Gmail/Drive/Slack) + prior notes."""
    key = f"{user.id}:{event_id}"

    if not refresh:
        cached = prep_ops.get_cached(db, user, event_id)
        if cached and prep_ops._usable(cached, user):  # fresh AND matches current persona
            # If the quick brief is cached but the richer version is still being researched, return
            # it with generating=true so the client shows it now and keeps polling for the upgrade.
            refining = key in _prep_refining
            return {**_prep_out(cached), "cached": True, "generating": refining, "partial": refining}
        err = _prep_error.get(key)
        if err:  # last build failed — surface it and stop the poll (a manual refresh retries)
            _prep_error.pop(key, None)
            return {"generating": False, "cached": False, "error": err}

    if key in _prep_inflight:  # phase 1 running, no brief yet — keep the client polling
        return {"generating": True, "cached": False}

    event = await _find_event(db, user, event_id)  # fast calendar lookup; validates access
    _prep_error.pop(key, None)
    _prep_inflight.add(key)
    task = asyncio.create_task(_generate_prep_bg(user.id, event))
    _prep_tasks.add(task)
    task.add_done_callback(_prep_tasks.discard)
    return {"generating": True, "cached": False}
