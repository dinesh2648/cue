"""Sales Copilot Pack — the shipped pilot, now expressed as a pack.

Wraps the existing Sales agent flow (intents → retrieve → answer → actions, two-tier with
Claude+MCP) behind the CopilotPack contract. Behavior is identical to pre-Phase-A.
"""
from __future__ import annotations

from ...agent import claude_agent, claude_sdk
from ...agent.intent import INTENT_DESCRIPTIONS, IntentResult, detect_intent
from ...agent.pipeline import pipeline
from ...agent.summary import generate_summary
from ...connectors import live_sources, manager
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

    def intent_descriptions(self) -> dict[str, str]:
        return INTENT_DESCRIPTIONS

    def has_deep(self, servers: list[dict], has_inprocess: bool = False) -> bool:
        # Deep runs when we can research SOMETHING live: a remote MCP server (Jira/GitHub/HubSpot/
        # Notion) OR an in-process source (Gmail/Drive/Slack). Either is enough for the agent tier.
        return claude_sdk.available() or (claude_agent.available() and (bool(servers) or has_inprocess))

    async def fast_answer(self, *, db, meeting, text, intent, doc_catalog) -> dict:
        # Persona is the pack itself (TechPack inherits this method → self.manifest.key == "tech").
        # Tech skips the sales CRM entirely and gets a tech-framed instant answer.
        persona = "tech" if self.manifest.key == "tech" else "sales"
        crm_context = {} if persona == "tech" else hubspot.company_context(db, meeting.crm_company_id)
        result = await pipeline.ainvoke(
            {"query_text": text, "crm_context": crm_context, "doc_catalog": doc_catalog, "persona": persona}
        )
        return {
            "answer": result.get("answer", ""),
            "evidence": result.get("evidence", []),
            "sources": result.get("sources", []),
            "confidence": result.get("confidence", 0.0),
            "actions": result.get("actions", []),
            "grounded": result.get("grounded", True),
        }

    async def deep_answer(self, *, db, meeting, text, intent, servers, context="") -> dict | None:
        if claude_sdk.available():
            # Pass the owner's connected remote MCP servers (HubSpot/…) plus their Google
            # Drive + Gmail tokens (read in-process — no hosted MCP), so the live copilot
            # researches across EVERY connected source, permission-scoped. `context` = the recent
            # conversation so the answer reflects the thread, not just the latest utterance.
            tk = await manager.inprocess_read_tokens(db, meeting.owner_user_id)
            return await claude_sdk.run_turn(
                text, intent.intent_type, meeting.crm_company_id, servers,
                drive_token=tk["google_drive"], gmail_token=tk["gmail"], slack_token=tk["slack"],
                context=context,
            )
        if claude_agent.available():
            # messages_mcp can't call Gmail/Drive/Slack (no hosted MCP) — pre-fetch their content
            # for THIS question and hand it in, so the live answer reasons over every connected
            # source. read_bodies=False keeps it snappy for the in-meeting SLA.
            comms = await live_sources.gather_comms(db, meeting.owner_user_id, text, read_bodies=False)
            if not servers and not comms:
                return None
            return await claude_agent.run_turn(
                text, intent.intent_type, servers, persona="sales", context=context, comms=comms,
            )
        return None

    async def summarize(self, *, meeting, intents, suggestions, crm, transcript, history=None, docs=None, persona="sales", comms=None) -> dict:
        return await generate_summary(
            meeting=meeting, intents=intents, suggestions=suggestions, crm=crm,
            transcript=transcript, history=history, docs=docs, persona=persona, comms=comms,
        )
