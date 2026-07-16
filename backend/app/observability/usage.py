"""LLM cost & token accounting (Phase 0 — measure first).

Every Claude/OpenAI call the app makes is recorded here: input/output tokens, cache
read/write tokens, MCP tool-call count, the call type (triage / deep_answer / meeting_context /
insights / summary / scorecard / prep / ask / …), the model, and the computed USD cost. Rows are
attributed to a meeting + user + org so an Owner/Admin can see exactly where spend goes and later
prove the effect of cost optimizations.

Recording is best-effort and never raises into the LLM path. The `LlmUsage` model lives here (a
separate module) rather than in models.py on purpose — it registers on the shared Base and is
picked up by create_all / Alembic exactly like any other table.
"""
from __future__ import annotations

import contextlib
import contextvars
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String, func, select
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base, SessionLocal

log = logging.getLogger("copilot.usage")

# When set (inside e.g. an "Ask Cue" request), every usage row recorded in that async context is
# bucketed under this call_type instead of its granular one — so all the LLM calls one Ask makes
# (triage + fast polish + deep answer + envelope) roll up into a single "ask" line, distinct from
# live-meeting spend. Propagates across awaits within the request; reset on scope exit.
_call_type_override: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "cue_call_type_override", default=None
)


@contextlib.contextmanager
def call_type_scope(call_type: str):
    """Bucket every LLM call recorded within this scope under `call_type` (e.g. "ask")."""
    token = _call_type_override.set(call_type)
    try:
        yield
    finally:
        _call_type_override.reset(token)


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class LlmUsage(Base):
    """One row per LLM API call — the raw material for the cost dashboard."""

    __tablename__ = "llm_usage"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    org_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    meeting_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    call_type: Mapped[str] = mapped_column(String(32), index=True)  # triage|deep_answer|summary|…
    model: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)  # MCP tool invocations this call
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


# ── Pricing (USD per 1M tokens) ───────────────────────────────────────────────
# Cache read ≈ 0.1× input; cache write (5-min TTL) ≈ 1.25× input. Match by prefix so dated model
# ids (e.g. claude-haiku-4-5-20251001) resolve. Tune here if Anthropic pricing changes.
_PER_M = 1_000_000
_PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6": {"in": 3.00, "out": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "claude-haiku-4-5":  {"in": 1.00, "out": 5.00,  "cache_read": 0.10, "cache_write": 1.25},
    "claude-opus-4":     {"in": 15.00, "out": 75.00, "cache_read": 1.50, "cache_write": 18.75},
    "gpt-4o-mini":       {"in": 0.15, "out": 0.60,  "cache_read": 0.15, "cache_write": 0.15},
}
_DEFAULT_PRICE = {"in": 3.00, "out": 15.00, "cache_read": 0.30, "cache_write": 3.75}  # sonnet-ish


def _price_for(model: str) -> dict[str, float]:
    m = (model or "").lower()
    for prefix, p in _PRICING.items():
        if m.startswith(prefix):
            return p
    return _DEFAULT_PRICE


def compute_cost(model: str, *, input_tokens: int, output_tokens: int,
                 cache_read_tokens: int = 0, cache_write_tokens: int = 0) -> float:
    p = _price_for(model)
    return round(
        (input_tokens * p["in"] + output_tokens * p["out"]
         + cache_read_tokens * p["cache_read"] + cache_write_tokens * p["cache_write"]) / _PER_M,
        6,
    )


def normalize_usage(raw) -> dict[str, int]:
    """Pull token counts out of an Anthropic/OpenAI usage object or dict into a common shape."""
    def g(key: str) -> int:
        if raw is None:
            return 0
        v = raw.get(key) if isinstance(raw, dict) else getattr(raw, key, None)
        try:
            return int(v or 0)
        except (TypeError, ValueError):
            return 0
    # OpenAI names its fields prompt_tokens / completion_tokens.
    return {
        "input_tokens": g("input_tokens") or g("prompt_tokens"),
        "output_tokens": g("output_tokens") or g("completion_tokens"),
        "cache_read_tokens": g("cache_read_input_tokens"),
        "cache_write_tokens": g("cache_creation_input_tokens"),
    }


def record_usage(
    *, call_type: str, model: str, usage,
    meeting_id: str | None = None, user_id: str | None = None, org_id: str | None = None,
    tool_calls: int = 0,
) -> None:
    """Persist one usage row. Best-effort — swallows every error so it can't break an LLM turn.
    `usage` may be an Anthropic/OpenAI usage object, a dict, or None. Missing org/user are derived
    from the meeting when possible."""
    try:
        override = _call_type_override.get()
        if override:
            call_type = override  # e.g. all calls inside an Ask request → the "ask" bucket
        tok = normalize_usage(usage)
        if not any(tok.values()) and not tool_calls:
            return  # nothing to record (e.g. offline fallback, no API call happened)
        db = SessionLocal()
        try:
            if meeting_id and (org_id is None or user_id is None):
                from ..models import Meeting  # local import: models.py is fine at runtime
                m = db.get(Meeting, meeting_id)
                if m is not None:
                    org_id = org_id or m.org_id
                    user_id = user_id or m.owner_user_id
            if org_id is None and user_id:  # no meeting (e.g. prep/ask) → derive org from the user
                from ..models import User
                u = db.get(User, user_id)
                if u is not None:
                    org_id = u.org_id
            cost = compute_cost(
                model,
                input_tokens=tok["input_tokens"], output_tokens=tok["output_tokens"],
                cache_read_tokens=tok["cache_read_tokens"], cache_write_tokens=tok["cache_write_tokens"],
            )
            db.add(LlmUsage(
                org_id=org_id, meeting_id=meeting_id, user_id=user_id,
                call_type=call_type, model=model,
                input_tokens=tok["input_tokens"], output_tokens=tok["output_tokens"],
                cache_read_tokens=tok["cache_read_tokens"], cache_write_tokens=tok["cache_write_tokens"],
                tool_calls=int(tool_calls or 0), cost_usd=cost,
            ))
            db.commit()
        finally:
            db.close()
    except Exception as exc:  # pragma: no cover - telemetry must never break the caller
        log.info("record_usage failed (%s/%s): %s", call_type, model, exc)


# ── Aggregation for the cost dashboard ────────────────────────────────────────
def org_cost_summary(db, org_id: str, *, days: int = 30) -> dict:
    """Totals + breakdowns (by model, call type, day, user, top meetings) for one org."""
    since = _now() - _td(days)
    base = (LlmUsage.org_id == org_id, LlmUsage.created_at >= since)

    totals = db.execute(
        select(
            func.count(LlmUsage.id), func.coalesce(func.sum(LlmUsage.cost_usd), 0.0),
            func.coalesce(func.sum(LlmUsage.input_tokens), 0), func.coalesce(func.sum(LlmUsage.output_tokens), 0),
            func.coalesce(func.sum(LlmUsage.cache_read_tokens), 0), func.coalesce(func.sum(LlmUsage.cache_write_tokens), 0),
        ).where(*base)
    ).one()

    def _group(col, label_key: str, limit: int | None = None, order_cost=True):
        stmt = (
            select(col, func.coalesce(func.sum(LlmUsage.cost_usd), 0.0), func.count(LlmUsage.id))
            .where(*base).group_by(col)
        )
        stmt = stmt.order_by(func.sum(LlmUsage.cost_usd).desc()) if order_cost else stmt.order_by(col)
        if limit:
            stmt = stmt.limit(limit)
        return [
            {label_key: (r[0] if r[0] is not None else "unknown"),
             "cost_usd": round(float(r[1]), 4), "calls": int(r[2])}
            for r in db.execute(stmt).all()
        ]

    by_model = _group(LlmUsage.model, "model")
    by_call_type = _group(LlmUsage.call_type, "call_type")
    by_user = _group(LlmUsage.user_id, "user_id", limit=50)
    # Only real meetings in the top-meetings table (drop the null bucket from prep/ask calls).
    top_meetings = [
        r for r in _group(LlmUsage.meeting_id, "meeting_id", limit=25)
        if r["meeting_id"] not in (None, "unknown")
    ][:20]

    # Daily series (portable date bucketing via func.date).
    day_rows = db.execute(
        select(func.date(LlmUsage.created_at), func.coalesce(func.sum(LlmUsage.cost_usd), 0.0), func.count(LlmUsage.id))
        .where(*base).group_by(func.date(LlmUsage.created_at)).order_by(func.date(LlmUsage.created_at))
    ).all()
    by_day = [{"date": str(r[0]), "cost_usd": round(float(r[1]), 4), "calls": int(r[2])} for r in day_rows]

    return {
        "days": days,
        "totals": {
            "calls": int(totals[0]), "cost_usd": round(float(totals[1]), 4),
            "input_tokens": int(totals[2]), "output_tokens": int(totals[3]),
            "cache_read_tokens": int(totals[4]), "cache_write_tokens": int(totals[5]),
        },
        "by_model": by_model,
        "by_call_type": by_call_type,
        "by_user": by_user,
        "top_meetings": top_meetings,
        "by_day": by_day,
    }


def _td(days: int):
    from datetime import timedelta
    return timedelta(days=max(1, min(days, 365)))
