"""Answer feedback loop — recall a user's past corrections and feed them back into new answers.

When a user corrects an answer, that correction is stored and then injected as authoritative
context into their future answers (live meeting + Ask), so the copilot stops repeating a
mistake it was told about. This is the "feed it back into retrieval + prompts" half of the loop.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import SuggestionFeedback


def recent_corrections_block(db: Session, user_id: str | None, limit: int = 5) -> str:
    """A prompt block of this user's most recent corrections, or "" if none."""
    if not user_id:
        return ""
    rows = list(
        db.scalars(
            select(SuggestionFeedback)
            .where(SuggestionFeedback.user_id == user_id, SuggestionFeedback.correction != "")
            .order_by(SuggestionFeedback.created_at.desc())
            .limit(limit)
        )
    )
    items = [(r.query_text or "", r.correction) for r in rows if r.correction]
    if not items:
        return ""
    lines = "\n".join(
        f'- When asked "{q[:140]}", the user says the correct answer is: {c[:400]}' for q, c in items
    )
    return (
        "The user has previously CORRECTED the copilot on the following. Treat these as "
        "authoritative and make sure your answer is consistent with them:\n" + lines
    )
