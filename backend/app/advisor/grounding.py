"""Grounding guardrails — keep every answer honestly tied to what we could actually see.

The product's whole promise is *grounded* answers. This module is the single place that
decides an answer's access scope and refuses to pass off seeded/sample data as the user's
real data. It is pure and dependency-free (stdlib only) so the rules can be unit-tested and
reasoned about in isolation, and so an eval harness can exercise them without a database.

The failure this prevents: a real, authenticated user with no connected sources getting a
confident answer composed from the seeded demo CRM (the "answered with Atlas Cloud demo
data" bug). For such a user we abstain honestly instead of guessing.

Access scopes (persisted on Suggestion.access_scope, rendered by the UI):
  USER — grounded live through the user's OWN connected tools (their permissions only)
  WEB  — grounded in live public-web research (not in their connected sources)
  DEMO — seeded / sample data; only legitimate in zero-credential demo mode
  NONE — nothing real to ground on → the copilot abstains
"""
from __future__ import annotations

USER = "user"
WEB = "web"
DEMO = "demo"
NONE = "none"

_GROUNDED_SCOPES = (USER, WEB, DEMO)

ABSTAIN_CONFIDENCE = 0.2
RESEARCHING_CONFIDENCE = 0.15


def fast_scope(*, dev_mode: bool, has_evidence: bool) -> str:
    """Honest scope the FAST (seeded/local) tier is allowed to claim.

    The fast tier only ever reads seeded CRM + local docs — never the user's live tools. So
    for a real authenticated user it is NEVER their data (→ NONE). In zero-cred demo mode the
    seeded data is the intended experience (→ DEMO when it actually cited something).
    """
    if dev_mode:
        return DEMO if has_evidence else NONE
    return NONE


def deep_scope(*, has_sources: bool, agent_scope: str | None = None) -> str:
    """Scope for the deep (agentic) tier.

    LIVE only if it actually retrieved something; preserve the agent's own USER-vs-WEB
    distinction (researching the web is grounded but is NOT the user's connected data).
    """
    if not has_sources:
        return NONE
    return agent_scope if agent_scope in (USER, WEB) else USER


def verify(*, answer: str, sources: list | None, evidence: list | None, scope: str) -> dict:
    """Cross-check an answer against its claimed scope.

    Returns {ok, scope, grounded, reason}. A grounded scope (USER/WEB/DEMO) MUST cite at
    least one source or piece of evidence; if it doesn't, it's downgraded to NONE
    (grounded=False) so an ungrounded answer can never masquerade as a cited one.
    """
    has_cite = bool(sources) or bool(evidence)
    if scope in _GROUNDED_SCOPES and not has_cite:
        return {"ok": False, "scope": NONE, "grounded": False,
                "reason": "claimed grounded but cited no source — downgraded to abstain"}
    if scope == NONE:
        return {"ok": True, "scope": NONE, "grounded": False, "reason": "no sources — abstained"}
    if not (answer or "").strip():
        return {"ok": False, "scope": NONE, "grounded": False, "reason": "empty answer"}
    return {"ok": True, "scope": scope, "grounded": True, "reason": ""}


def _phrase(names: list[str] | None) -> str:
    items = [n for n in (names or []) if n][:3]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " or " + items[-1]


def abstain_answer(missing: list[str] | None = None) -> dict:
    """The honest 'I can't ground this' answer for a real user with no live sources."""
    tools = _phrase(missing)
    hint = (f" Connect {tools} and I'll answer from your own data."
            if tools else " Connect your tools and I'll answer from your own data.")
    return {
        "answer": "I don't have this in your connected sources, so I won't guess." + hint,
        "evidence": [],
        "sources": [],
        "confidence": ABSTAIN_CONFIDENCE,
        "actions": [],
        "grounded": False,
        "access_scope": NONE,
    }


def researching_answer(sources: list[str] | None = None) -> dict:
    """Placeholder shown to a real user for the instant tier while the deep tier searches
    their live sources — honest ('searching…') instead of a seeded stand-in answer."""
    tools = _phrase(sources)
    where = f" across your {tools}" if tools else " across your connected sources"
    return {
        "answer": f"Searching{where}…",
        "evidence": [],
        "sources": [],
        "confidence": RESEARCHING_CONFIDENCE,
        "actions": [],
        "grounded": False,
        "access_scope": NONE,
    }
