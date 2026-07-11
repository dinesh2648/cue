"""Per-user capability toggles — each user enables/disables individual copilot behaviours.

Stored as a JSON dict on User.capabilities; any missing key falls back to the default here,
so a newly-added capability lights up 'on' for everyone without a data migration.
"""
from __future__ import annotations

# key → (default_on, label, description) — the catalog the Settings UI renders.
CAPABILITIES: dict[str, tuple[bool, str, str]] = {
    "action_confirmations": (
        True, "Action confirmations",
        "Show a clear confirmation of exactly what was written after you approve an action.",
    ),
    "action_undo": (
        True, "Undo actions",
        "Offer an Undo for writes that can be reversed — delete the ticket/note/draft/event, archive the doc.",
    ),
    "recap_links": (
        True, "Link actions into the recap",
        "List everything created from a meeting, with links, in its recap.",
    ),
    "answer_feedback": (
        True, "Answer feedback",
        "Rate or correct live answers; your corrections steer the copilot's future answers.",
    ),
}

DEFAULTS: dict[str, bool] = {k: v[0] for k, v in CAPABILITIES.items()}


def resolve(user) -> dict[str, bool]:
    """The user's capabilities merged over defaults (absent/unknown keys default sensibly)."""
    stored = dict(getattr(user, "capabilities", None) or {})
    return {k: bool(stored.get(k, d)) for k, d in DEFAULTS.items()}


def enabled(user, key: str) -> bool:
    """Is this capability on for the user? Defaults to on for unknown keys/absent config."""
    stored = dict(getattr(user, "capabilities", None) or {})
    return bool(stored.get(key, DEFAULTS.get(key, True)))


def catalog() -> list[dict]:
    """[{key, label, description, default}] for the Settings UI."""
    return [
        {"key": k, "label": lbl, "description": desc, "default": d}
        for k, (d, lbl, desc) in CAPABILITIES.items()
    ]
