"""Proactive Insights agent.

Without waiting to be asked, it watches the meeting and surfaces gaps the participants might miss:
a decision made without an owner, an action item with no assignee, an unanswered question, a risk
or blocker, a contradiction, a deadline with no plan. Non-intrusive — the UI shows them as
dismissible cards. Grounded strictly in the transcript + evolving state; it never invents.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import select

from ..db import SessionLocal
from ..integrations.llm import llm_complete
from ..models import Meeting, TranscriptSegment

log = logging.getLogger("copilot.insights")

_TYPES = {
    "decision_without_owner", "unassigned_action", "open_question", "risk",
    "contradiction", "deadline", "missing_stakeholder", "follow_up",
}

_SYSTEM = (
    "You are a proactive meeting assistant. Given the evolving meeting state and recent transcript, "
    "surface only GENUINELY useful gaps the participants may have missed — do not restate what's "
    "already handled. Return JSON ONLY: {\"insights\": [{\"type\": <one of "
    "decision_without_owner|unassigned_action|open_question|risk|contradiction|deadline|"
    "missing_stakeholder|follow_up>, \"severity\": <info|warn|high>, \"text\": <one concise, "
    "specific sentence>}]}. At most 4, highest-value first. [] if nothing is worth surfacing. "
    "Ground strictly in the material — never invent owners, dates, or facts."
)


async def detect(meeting_id: str) -> list[dict]:
    """Compute proactive insights for a meeting, persist them on the meeting, and return them.
    Self-contained (own session) for background use; best-effort — [] on any failure."""
    db = SessionLocal()
    try:
        meeting = db.get(Meeting, meeting_id)
        if meeting is None:
            return []
        state = meeting.context_json or {}
        # Need at least some captured state or transcript to reason about.
        segs = list(
            db.scalars(
                select(TranscriptSegment)
                .where(TranscriptSegment.meeting_id == meeting_id)
                .order_by(TranscriptSegment.ts.desc())
                .limit(30)
            )
        )
        if not segs:
            return []
        transcript = "\n".join(f"{s.speaker} ({s.role}): {s.text}" for s in reversed(segs))[-4000:]
        state_block = json.dumps({k: state.get(k) for k in (
            "current_topic", "open_questions", "decisions", "risks", "action_items", "entities"
        )})[:2500]
        # Insights are shared (broadcast to the room) — write them in the meeting owner's language.
        from .profiles import language_directive
        from ..models import User as _User
        owner = db.get(_User, meeting.owner_user_id) if meeting.owner_user_id else None
        lang = language_directive(owner)
        raw = await llm_complete(
            system=_SYSTEM + (("\n" + lang) if lang else ""),
            user=f"Meeting state:\n{state_block}\n\nRecent transcript:\n{transcript}\n\nReturn the JSON insights.",
            max_tokens=500,
            temperature=0.2,
            timeout=25.0,
            call_type="insights",
            meeting_id=meeting_id,
        )
        if not raw:
            return []
        try:
            data = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
        except (ValueError, json.JSONDecodeError):
            return []
        items: list[dict] = []
        for it in (data.get("insights") or [])[:4]:
            text = str(it.get("text") or "").strip()
            if not text:
                continue
            typ = it.get("type") if it.get("type") in _TYPES else "follow_up"
            sev = it.get("severity") if it.get("severity") in ("info", "warn", "high") else "info"
            items.append({"type": typ, "severity": sev, "text": text[:240]})
        # Persist the latest set on the meeting (survives context refreshes via the merge in
        # meeting_context.refresh) so a late-joining UI can render them on load.
        ctx = dict(meeting.context_json or {})
        ctx["insights"] = items
        meeting.context_json = ctx
        db.add(meeting)
        db.commit()
        log.info("insights %s: %d surfaced", meeting_id, len(items))
        return items
    except Exception as exc:  # pragma: no cover - best-effort background task
        log.info("insights failed for %s: %s", meeting_id, exc)
        return []
    finally:
        db.close()
