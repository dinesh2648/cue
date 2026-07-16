"""Advisory Orchestrator — the single reasoning path for one turn.

Coordinates the agents: Intent is decided upstream (triage), then Retrieval Orchestrator gathers
role-scoped context, the Advisory agent produces the grounded answer, and the envelope adds
assumptions/risks/next-actions. Packs are thin adapters — they only choose persona/department and
delegate here, so the intelligence lives in one place instead of being duplicated per pack.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from ..agent import claude_agent, claude_sdk
from ..connectors import manager
from ..models import Organization, User
from . import advisory, meeting_context
from . import retrieval as retrieval_agent
from .profiles import advisory_preamble
from .roles import filter_servers_for_role

log = logging.getLogger("copilot.orchestrator")


async def run(
    *, db: Session, meeting, text: str, intent, servers: list[dict], context: str = "",
    persona: str = "sales", with_envelope: bool = True,
) -> dict | None:
    """Deep (agentic) answer for one turn, or None to fall back to the fast tier.

    with_envelope adds assumptions/risks/next_actions (one extra fast pass) — on for Ask + live
    deep answers, which are already off the SLA-critical path.
    """
    uid = getattr(meeting, "owner_user_id", None)

    # ── Agent-SDK path (local dev only; the image ships messages_mcp) ──────────
    if claude_sdk.available():
        user = db.get(User, uid) if uid else None
        org = db.get(Organization, user.org_id) if user and user.org_id else None
        tk = (await manager.inprocess_read_tokens(db, uid)) if uid else {"google_drive": None, "gmail": None, "slack": None}
        srv = filter_servers_for_role(user, servers)
        pre = "\n\n".join(x for x in [advisory_preamble(user, org), meeting_context.render(meeting), context] if x).strip()
        res = await claude_sdk.run_turn(
            text, intent.intent_type, getattr(meeting, "crm_company_id", None), srv, persona=persona,
            drive_token=tk["google_drive"], gmail_token=tk["gmail"], slack_token=tk["slack"], context=pre,
        )
        if res and with_envelope:
            res.update(await advisory.envelope(text, res.get("answer", ""), res.get("evidence", [])))
        return res

    # ── messages_mcp path (the shipped engine) ────────────────────────────────
    if not claude_agent.available():
        return None
    r = await retrieval_agent.gather(db, meeting, text, servers)
    if not r.has_sources:
        return None
    res = await advisory.respond(
        text, intent.intent_type, persona, r, context,
        meeting_id=getattr(meeting, "id", None), user_id=uid,
    )
    if res and with_envelope:
        res.update(await advisory.envelope(text, res.get("answer", ""), res.get("evidence", [])))
    return res
