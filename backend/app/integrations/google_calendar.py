"""Google Calendar API — read the signed-in user's upcoming events with their OAuth token.

Direct REST (no MCP needed for read): GET the primary calendar's events, normalize
them, and pull out a video-meeting URL (Google Meet / Zoom / Teams) when present so the
user can dispatch the copilot straight from an upcoming meeting.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

import httpx

log = logging.getLogger("copilot.gcal")

_EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
_TIMEOUT = httpx.Timeout(12.0, connect=5.0)
_MEET_RE = re.compile(
    r"https?://[^\s<>\"]+(?:meet\.google\.com|zoom\.us|teams\.microsoft\.com|teams\.live\.com)[^\s<>\"]*",
    re.IGNORECASE,
)


def _meeting_url(ev: dict) -> str:
    """Best-effort video-call link for an event."""
    if ev.get("hangoutLink"):
        return ev["hangoutLink"]
    for ep in (ev.get("conferenceData") or {}).get("entryPoints", []) or []:
        if ep.get("entryPointType") == "video" and ep.get("uri"):
            return ep["uri"]
    for field in (ev.get("location"), ev.get("description")):
        if field and (m := _MEET_RE.search(field)):
            return m.group(0)
    return ""


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


async def create_event(token: str, title: str, description: str = "", in_hours: int = 24, minutes: int = 30) -> dict:
    """Create a calendar event (used for reminders/follow-ups). Returns {id, url}."""
    start = datetime.now(timezone.utc) + timedelta(hours=in_hours)
    end = start + timedelta(minutes=minutes)
    body = {
        "summary": title[:300],
        "description": description[:2000],
        "start": {"dateTime": _iso_z(start)},
        "end": {"dateTime": _iso_z(end)},
        "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 30}]},
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(_EVENTS_URL, headers={"Authorization": f"Bearer {token}"}, json=body)
        resp.raise_for_status()
        data = resp.json()
    return {"id": data.get("id"), "url": data.get("htmlLink", "")}


async def delete_event(token: str, event_id: str) -> None:
    """Undo a calendar write — delete an event by id. 404/410 = already gone (treated as done)."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.delete(f"{_EVENTS_URL}/{event_id}", headers={"Authorization": f"Bearer {token}"})
        if resp.status_code not in (200, 204, 404, 410):
            resp.raise_for_status()


async def list_upcoming(token: str, max_results: int = 8, days: int = 30) -> list[dict]:
    """Upcoming events on the user's primary calendar, soonest first.

    Raises httpx.HTTPStatusError on API errors (caller maps to a friendly message).
    """
    now = datetime.now(timezone.utc)
    params = {
        "timeMin": _iso_z(now),
        "timeMax": _iso_z(now + timedelta(days=days)),
        "maxResults": str(max_results),
        "singleEvents": "true",
        "orderBy": "startTime",
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(_EVENTS_URL, params=params, headers={"Authorization": f"Bearer {token}"})
        resp.raise_for_status()
        data = resp.json()

    events: list[dict] = []
    for ev in data.get("items", []):
        if ev.get("status") == "cancelled":
            continue
        start, end = ev.get("start", {}) or {}, ev.get("end", {}) or {}
        events.append(
            {
                "id": ev.get("id"),
                "title": ev.get("summary") or "(no title)",
                "start": start.get("dateTime") or start.get("date") or "",
                "end": end.get("dateTime") or end.get("date") or "",
                "all_day": "date" in start and "dateTime" not in start,
                "attendees": [a.get("email", "") for a in (ev.get("attendees") or []) if a.get("email")],
                "organizer": (ev.get("organizer") or {}).get("email", ""),
                "meeting_url": _meeting_url(ev),
                "html_link": ev.get("htmlLink", ""),
            }
        )
    return events
