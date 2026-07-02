"""Tech Copilot Pack — for engineering/technical meetings.

Same real-time substrate as Sales (triage → two-tier answer → summary) but with a
technical persona and taxonomy. The deep agent uses the engineer's connected tools —
Jira, GitHub, Notion, Drive, docs, WebSearch — and never CRM/LinkedIn.
"""
from __future__ import annotations

from ...agent import claude_agent, claude_sdk
from ...agent.intent import TECH_INTENT_DESCRIPTIONS
from ...connectors import manager
from ..base import PackManifest
from ..sales import SalesPack


class TechPack(SalesPack):
    manifest = PackManifest(
        key="tech",
        name="Tech",
        persona="Engineer / Tech Lead",
        description=(
            "Real-time engineering meeting copilot — captures requirements, answers architecture/API/"
            "bug/ticket questions from Jira, GitHub, docs and the web, and writes the recap + Jira-ready "
            "action items afterwards. (Reuses the Sales substrate with a technical persona.)"
        ),
    )

    def intent_descriptions(self) -> dict[str, str]:
        return TECH_INTENT_DESCRIPTIONS

    async def deep_answer(self, *, db, meeting, text, intent, servers, context="") -> dict | None:
        if claude_sdk.available():
            # Tech copilot also reads the engineer's Drive + Gmail (in-process). LinkedIn is
            # excluded inside run_turn for the tech persona; everything else is included.
            # `context` = the recent conversation so the answer reflects the thread.
            tk = await manager.inprocess_read_tokens(db, meeting.owner_user_id)
            return await claude_sdk.run_turn(
                text, intent.intent_type, meeting.crm_company_id, servers, persona="tech",
                drive_token=tk["google_drive"], gmail_token=tk["gmail"], slack_token=tk["slack"],
                context=context,
            )
        if claude_agent.available() and servers:
            return await claude_agent.run_turn(
                text, intent.intent_type, servers, persona="tech", context=context
            )
        return None
