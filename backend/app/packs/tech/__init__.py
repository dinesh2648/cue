"""Tech Copilot Pack — for engineering/technical meetings.

Same real-time substrate as Sales (triage → two-tier answer → summary) but with a technical
persona and taxonomy. deep_answer + summarize are inherited from SalesPack: the advisor
orchestrator derives the persona from this pack's key ("tech") and role-scopes the tools
(Jira/GitHub in, CRM out) automatically.
"""
from __future__ import annotations

from ...agent.intent import TECH_INTENT_DESCRIPTIONS
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
