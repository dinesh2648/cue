"""Meeting Context Manager — the evolving state of a live meeting.

Instead of reasoning only over the latest utterance, the advisor keeps a running picture of the
WHOLE meeting: a rolling summary plus structured state (current topic, open questions, decisions,
risks, action items, referenced entities). It's refreshed periodically from the transcript and fed
into every live answer, so "what did we decide?" / "who owns this?" have real grounding.

The state persists on the Meeting row (running_summary + context_json), so it survives reconnects
and is available to the post-meeting write-up too.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import select

from ..db import SessionLocal
from ..integrations.llm import llm_complete
from ..models import Meeting, TranscriptSegment

log = logging.getLogger("copilot.meeting_context")

_REFRESH_EVERY = 6  # transcript segments between refreshes — bounds cost/latency
_STATE_KEYS = ("current_topic", "previous_topics", "open_questions", "decisions", "risks",
               "action_items", "entities")

_SYSTEM = (
    "You maintain the live STATE of a meeting for an AI advisor. Given the running summary + state "
    "so far and the latest transcript, return an UPDATED, compact state as JSON only. MERGE with the "
    "prior state — never drop decisions or action items that were already captured. Keys:\n"
    "- running_summary: <=6 sentences, what has happened and where things stand.\n"
    "- current_topic: what's being discussed right now.\n"
    "- previous_topics: array of earlier topics.\n"
    "- open_questions: array of unanswered questions raised.\n"
    "- decisions: array of concrete decisions/agreements.\n"
    "- risks: array of risks, blockers or concerns.\n"
    "- action_items: array of 'task — owner' (include owner when stated, else just the task).\n"
    "- entities: object with arrays customers, projects, tickets, documents, people.\n"
    "Ground strictly in the transcript — never invent names, numbers or decisions. JSON only."
)


def should_refresh(seg_count: int) -> bool:
    """True every _REFRESH_EVERY segments — the engine calls this to decide when to update."""
    return seg_count > 0 and seg_count % _REFRESH_EVERY == 0


def render(meeting) -> str:
    """Compact prompt block of the current meeting state — '' when nothing's captured yet.
    Safe on a meeting-less shim (Ask): getattr defaults make it a no-op."""
    running = (getattr(meeting, "running_summary", "") or "").strip()
    ctx = getattr(meeting, "context_json", None) or {}
    if not running and not any(ctx.get(k) for k in _STATE_KEYS):
        return ""
    lines = ["## Meeting so far (evolving context)"]
    if running:
        lines.append(running)

    def _add(label: str, key: str) -> None:
        v = ctx.get(key)
        if not v:
            return
        if isinstance(v, list):
            items = [str(x).strip() for x in v if str(x).strip()]
            if items:
                lines.append(f"{label}: " + "; ".join(items[:10]))
        elif str(v).strip():
            lines.append(f"{label}: {str(v).strip()}")

    _add("Current topic", "current_topic")
    _add("Open questions", "open_questions")
    _add("Decisions so far", "decisions")
    _add("Risks", "risks")
    _add("Action items", "action_items")
    ent = ctx.get("entities") or {}
    flat = [f"{k}: {', '.join(str(x) for x in v[:6])}" for k, v in ent.items() if v]
    if flat:
        lines.append("Referenced: " + " | ".join(flat))
    return "\n".join(lines)


async def refresh(meeting_id: str) -> None:
    """Re-derive the meeting state from the full transcript (self-contained — own DB session, for
    background use). Best-effort: any failure leaves the previous state untouched."""
    db = SessionLocal()
    try:
        meeting = db.get(Meeting, meeting_id)
        if meeting is None:
            return
        segs = list(
            db.scalars(
                select(TranscriptSegment)
                .where(TranscriptSegment.meeting_id == meeting_id)
                .order_by(TranscriptSegment.ts)
            )
        )
        if not segs:
            return
        transcript = "\n".join(f"{s.speaker} ({s.role}): {s.text}" for s in segs)[-6000:]
        prior = ((meeting.running_summary or "") + "\n" + json.dumps(meeting.context_json or {}))[:3000]
        raw = await llm_complete(
            system=_SYSTEM,
            user=f"Prior summary + state:\n{prior}\n\nLatest transcript:\n{transcript}\n\nReturn the updated JSON state.",
            max_tokens=900,
            temperature=0.2,
            timeout=30.0,
        )
        if not raw:
            return
        try:
            data = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
        except (ValueError, json.JSONDecodeError):
            return
        meeting.running_summary = (data.get("running_summary") or meeting.running_summary or "")[:2000]
        prev = meeting.context_json or {}
        meeting.context_json = {k: (data.get(k) if data.get(k) is not None else prev.get(k)) for k in _STATE_KEYS}
        db.add(meeting)
        db.commit()
        ctx = meeting.context_json
        log.info(
            "meeting_context refreshed %s: topic=%r decisions=%d actions=%d",
            meeting_id, ctx.get("current_topic", ""),
            len(ctx.get("decisions") or []), len(ctx.get("action_items") or []),
        )
    except Exception as exc:  # pragma: no cover - best-effort background task
        log.info("meeting_context refresh failed for %s: %s", meeting_id, exc)
    finally:
        db.close()
