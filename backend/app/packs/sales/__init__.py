"""Sales Copilot Pack — the shipped pilot, now expressed as a pack.

Wraps the existing Sales agent flow (intents → retrieve → answer → actions, two-tier with
Claude+MCP) behind the CopilotPack contract. Behavior is identical to pre-Phase-A.
"""
from __future__ import annotations

from ...agent import claude_agent, claude_sdk
from ...agent.intent import IntentResult, detect_intent
from ...agent.pipeline import pipeline
from ...agent.summary import generate_summary
from ...integrations import hubspot
from ..base import CopilotPack, PackManifest


class SalesPack(CopilotPack):
    manifest = PackManifest(
        key="sales",
        name="Sales",
        persona="Sales rep / Sales Engineer",
        description=(
            "Real-time sales meeting copilot — answers contract, security, pricing, support and "
            "renewal questions from CRM + enterprise docs, and automates the post-meeting CRM follow-up."
        ),
    )

    def detect(self, text: str) -> IntentResult:
        return detect_intent(text)

    def has_deep(self, servers: list[dict]) -> bool:
        return claude_sdk.available() or (claude_agent.available() and bool(servers))

    async def fast_answer(self, *, db, meeting, text, intent, doc_catalog) -> dict:
        crm_context = hubspot.company_context(db, meeting.crm_company_id)
        result = await pipeline.ainvoke(
            {"query_text": text, "crm_context": crm_context, "doc_catalog": doc_catalog}
        )
        return {
            "answer": result.get("answer", ""),
            "evidence": result.get("evidence", []),
            "sources": result.get("sources", []),
            "confidence": result.get("confidence", 0.0),
            "actions": result.get("actions", []),
            "grounded": result.get("grounded", True),
        }

    async def deep_answer(self, *, db, meeting, text, intent, servers) -> dict | None:
        if claude_sdk.available():
            return await claude_sdk.run_turn(text, intent.intent_type, meeting.crm_company_id)
        if claude_agent.available() and servers:
            return await claude_agent.run_turn(text, intent.intent_type, servers)
        return None

    async def summarize(self, *, meeting, intents, suggestions, crm, transcript) -> dict:
        return await generate_summary(
            meeting=meeting, intents=intents, suggestions=suggestions, crm=crm, transcript=transcript
        )
