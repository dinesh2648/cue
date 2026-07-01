"""Auto-pilot — removes the manual 'send copilot' and 'end & summarize' steps.

A single background loop (started in main.lifespan) does two things every tick:
  1. Auto-join: for users with autopilot ON + a connected Google Calendar, dispatch a
     Recall bot to imminent meetings that have a video link — filtered to EXTERNAL
     meetings (≥1 attendee outside the user's email domain) so it skips internal standups.
  2. Auto-finalize: for live meetings whose Recall bot has left the call, auto-run the
     summary + CRM automation + rep scorecard (no 'End' click).

Best-effort and defensive: any per-item failure is logged and skipped.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from .config import settings
from .connectors import manager as conn_manager
from .db import SessionLocal
from .integrations import google_calendar, recall
from .meetings_ops import finalize_meeting
from .models import Meeting, User
from .packs.registry import pack_for_team

log = logging.getLogger("copilot.autopilot")

_TICK_SECONDS = 60
_JOIN_WINDOW_MIN = 5  # dispatch the bot when a meeting starts within this many minutes
_PREP_WINDOW_MIN = 60  # pre-generate prep ~30-60 min ahead: start once a meeting is within this window
_PREP_REFRESH_MIN = 90  # regenerate if the cached brief is older than this, so it's fresh near start
_ENDED_CODES = {"call_ended", "done", "fatal"}

# Event ids currently being prepped (best-effort, per-process) so overlapping ticks don't
# kick off duplicate agent runs for the same upcoming meeting.
_prep_inflight: set[str] = set()
_prep_tasks: set[asyncio.Task] = set()


def _domain(email: str) -> str:
    return email.split("@", 1)[1].lower() if "@" in email else ""


_LATE_JOIN_GRACE_MIN = 20  # join meetings with no end time that started within this many minutes


def _within_join_window(mins_to_start: float, end_str: str | None, now: datetime) -> bool:
    """True if a meeting should be auto-joined now: it starts within the window, OR it's
    already in progress and hasn't ended yet (so late starts / mid-call enables still join)."""
    if mins_to_start > _JOIN_WINDOW_MIN:
        return False  # caller already guards this, but keep the function self-contained
    if end_str:
        try:
            end = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
            return now < end  # ongoing — join until the meeting actually ends
        except ValueError:
            pass
    return mins_to_start >= -_LATE_JOIN_GRACE_MIN  # no usable end time → grace window


def _external_only() -> bool:
    """When set, autopilot only joins customer-facing (external) meetings (legacy behaviour)."""
    import os

    return os.getenv("AUTOPILOT_EXTERNAL_ONLY", "").lower() in ("1", "true", "yes")


def _is_external(attendees: list[str], organizer: str, rep_email: str) -> bool:
    """True if anyone on the invite is outside the rep's company domain."""
    rep_dom = _domain(rep_email)
    if not rep_dom:
        return False
    for a in [*attendees, organizer]:
        d = _domain(a)
        if d and d != rep_dom:
            return True
    return False


async def _auto_join(db) -> None:
    if not recall.enabled():
        return
    now = datetime.now(timezone.utc)
    users = list(db.scalars(select(User).where(User.autopilot.is_(True))))
    for user in users:
        token = await conn_manager.get_access_token(db, user.id, "google_calendar")
        if not token or token.startswith("demo-"):
            continue
        try:
            events = await google_calendar.list_upcoming(token, max_results=10, days=1)
        except Exception as exc:  # pragma: no cover
            log.info("autopilot calendar read failed for %s: %s", user.id, exc)
            continue
        for ev in events:
            if not ev.get("meeting_url") or not ev.get("start"):
                continue
            try:
                start = datetime.fromisoformat(ev["start"].replace("Z", "+00:00"))
            except ValueError:
                continue
            mins = (start - now).total_seconds() / 60
            if mins > _JOIN_WINDOW_MIN:  # starts too far in the future
                continue
            # Join in-progress meetings too: from _JOIN_WINDOW_MIN before start until the
            # event's end. So a late start, a missed tick, or enabling autopilot mid-call still
            # gets a copilot. Fall back to a grace window if the event has no end time.
            if not _within_join_window(mins, ev.get("end"), now):
                continue
            # Join both internal and external meetings — skip only solo events / personal holds
            # (a Meet link with no one else on the invite). Set AUTOPILOT_EXTERNAL_ONLY=1 to
            # restrict back to customer-facing (external) meetings only.
            others = [a for a in (ev.get("attendees") or []) if a and a != user.email]
            if not others:
                continue
            if _external_only() and not _is_external(ev.get("attendees", []), ev.get("organizer", ""), user.email):
                continue
            # One copilot per meeting: skip if a bot is already (or was) on this event OR url.
            # Scope to the user's org so two tenants who happen to share a meeting URL
            # (e.g. a recurring vendor link) don't suppress each other's copilots.
            dup = db.scalar(
                select(Meeting).where(
                    Meeting.org_id == user.org_id,
                    (Meeting.calendar_event_id == ev["id"]) | (Meeting.meeting_url == ev["meeting_url"]),
                )
            )
            if dup:
                # Make sure this attendee can see the shared meeting.
                if user.email and user.email not in (dup.attendees or []):
                    dup.attendees = [*(dup.attendees or []), user.email]
                    db.commit()
                continue
            await _dispatch(db, user, ev)


async def _dispatch(db, user: User, ev: dict) -> None:
    meeting = Meeting(
        title=ev.get("title") or "Customer meeting",
        platform="google_meet",
        customer_contact=next((a for a in ev.get("attendees", []) if _domain(a) != _domain(user.email)), ""),
        rep_name=user.name or user.email,
        status="live",
        owner_user_id=user.id,
        org_id=user.org_id,
        pack=pack_for_team(user.team),  # Sales vs Tech copilot by the dispatcher's team
        meeting_url=ev["meeting_url"],
        calendar_event_id=ev["id"],
        attendees=ev.get("attendees", []),
    )
    db.add(meeting)
    db.commit()
    try:
        bot = await recall.create_bot(ev["meeting_url"], meeting.id)
        meeting.recall_bot_id = bot.get("id")
        db.commit()
        log.info("autopilot dispatched bot for %s (%s)", meeting.title, meeting.id)
    except Exception as exc:  # pragma: no cover
        meeting.status = "scheduled"
        db.commit()
        log.warning("autopilot dispatch failed for %s: %s", meeting.id, exc)


async def _auto_prep(db) -> None:
    """Pre-generate prep briefs ~30-60 min ahead of every meeting so they're ready on open.

    Fires once a meeting is within _PREP_WINDOW_MIN, for internal + external meetings with
    another attendee. Regenerates if the cached brief is stale (> _PREP_REFRESH_MIN old) so
    it reflects the latest email/CRM context near start. Each brief runs as a background task
    (the agent is slow) and never stalls the join/finalize loop.
    """
    from . import prep_ops

    now = datetime.now(timezone.utc)
    users = list(db.scalars(select(User).where(User.autopilot.is_(True))))
    for user in users:
        token = await conn_manager.get_access_token(db, user.id, "google_calendar")
        if not token or token.startswith("demo-"):
            continue
        try:
            events = await google_calendar.list_upcoming(token, max_results=10, days=1)
        except Exception:  # pragma: no cover
            continue
        for ev in events:
            eid = ev.get("id")
            if not eid or not ev.get("start") or eid in _prep_inflight:
                continue
            try:
                start = datetime.fromisoformat(ev["start"].replace("Z", "+00:00"))
            except ValueError:
                continue
            mins = (start - now).total_seconds() / 60
            if mins < -2 or mins > _PREP_WINDOW_MIN:  # not in the ~30-60-min-ahead window
                continue
            # Prep every meeting (internal + external) with someone else on it; skip solo holds.
            others = [a for a in (ev.get("attendees") or []) if a and a != user.email]
            if not others:
                continue
            if _external_only() and not _is_external(ev.get("attendees", []), ev.get("organizer", ""), user.email):
                continue
            cached = prep_ops.get_cached(db, user, eid)
            if cached and cached.generated_at and (cached.persona or "") == prep_ops._persona(user):
                gen = cached.generated_at if cached.generated_at.tzinfo else cached.generated_at.replace(tzinfo=timezone.utc)
                if (now - gen).total_seconds() < _PREP_REFRESH_MIN * 60:
                    continue  # already prepared recently for the current persona
            _prep_inflight.add(eid)
            task = asyncio.create_task(_prep_one(user.id, ev))
            _prep_tasks.add(task)
            task.add_done_callback(_prep_tasks.discard)


async def _prep_one(user_id: str, ev: dict) -> None:
    """Generate one prep brief in its own DB session (off the main loop)."""
    from . import prep_ops

    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if user:
            await prep_ops.build_prep(db, user, ev)
            log.info("autopilot pre-generated prep for event %s", ev.get("id"))
    except Exception as exc:  # pragma: no cover
        log.info("autopilot prep failed for %s: %s", ev.get("id"), exc)
    finally:
        db.close()
        _prep_inflight.discard(ev.get("id"))


async def _auto_finalize(db) -> None:
    if not recall.enabled():
        return
    live = list(
        db.scalars(select(Meeting).where(Meeting.status == "live", Meeting.recall_bot_id.is_not(None)))
    )
    for meeting in live:
        try:
            status = await recall.get_bot_status(meeting.recall_bot_id)
        except Exception:  # pragma: no cover
            continue
        if status in _ENDED_CODES:
            log.info("autopilot finalizing %s (bot %s)", meeting.id, status)
            try:
                await finalize_meeting(db, meeting, with_scorecard=True)
            except Exception as exc:  # pragma: no cover
                log.warning("autopilot finalize failed for %s: %s", meeting.id, exc)


async def _tick() -> None:
    db = SessionLocal()
    try:
        await _auto_join(db)
        await _auto_prep(db)
        await _auto_finalize(db)
    finally:
        db.close()


async def run_loop() -> None:
    """Background loop; started from the app lifespan. Self-healing per tick."""
    log.info("auto-pilot loop started (every %ss)", _TICK_SECONDS)
    while True:
        try:
            await _tick()
        except Exception as exc:  # pragma: no cover - never let the loop die
            log.warning("auto-pilot tick error: %s", exc)
        await asyncio.sleep(_TICK_SECONDS)
