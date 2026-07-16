"""The Copilot Pack contract — the interface every vertical implements.

The substrate (realtime engine) is pack-agnostic: it calls `detect` per turn, then the
two-tier `fast_answer`/`deep_answer`, and `summarize` at the end. A new vertical = a new
`CopilotPack` subclass + its connectors. (Phase A; see docs/PLATFORM_EXTENSIBILITY.md.)
"""
from __future__ import annotations

from dataclasses import dataclass

from ..agent.intent import IntentResult


@dataclass
class PackManifest:
    key: str  # "sales" | "developer" | "product" | "csm"
    name: str
    persona: str
    description: str


class CopilotPack:
    """Base class for a vertical copilot. Subclasses set `manifest` and implement the flow."""

    manifest: PackManifest

    # ── Triggers ──────────────────────────────────────────────────────────────
    def detect(self, text: str) -> IntentResult:
        """Fast, offline regex classification into this pack's intent taxonomy."""
        raise NotImplementedError

    def intent_descriptions(self) -> dict[str, str]:
        """intent_type → human description, used to prompt the LLM triage layer."""
        return {"general": "any genuine question or request the rep should answer"}

    async def classify(self, text: str, recent: list[str] | None = None,
                       meeting_id: str | None = None) -> IntentResult:
        """Layer 1: LLM triage (Claude) decides if/what to answer; regex is the fallback."""
        from ..agent import triage

        res = await triage.classify(text, recent, self.intent_descriptions(), meeting_id=meeting_id)
        return res if res is not None else self.detect(text)

    # ── Capability ────────────────────────────────────────────────────────────
    def has_deep(self, servers: list[dict], has_inprocess: bool = False) -> bool:
        """Whether a deep (agentic) second tier will run for this turn.
        `has_inprocess` = the user has connected Gmail/Drive/Slack (read in-process, no hosted MCP),
        which is enough to deepen an answer even without any remote-MCP server."""
        return False

    # ── Inline flow (real-time, two-tier) ──────────────────────────────────────
    async def fast_answer(
        self, *, db, meeting, text: str, intent: IntentResult, doc_catalog: list[dict]
    ) -> dict:
        """Tier 1: instant grounded answer. Returns {answer, evidence, sources, confidence, actions}."""
        raise NotImplementedError

    async def deep_answer(
        self, *, db, meeting, text: str, intent: IntentResult, servers: list[dict], context: str = ""
    ) -> dict | None:
        """Tier 2: richer agentic answer that upgrades the card in place (or None to skip).
        `context` is the recent conversation so the answer reflects the thread, not one utterance."""
        return None

    # ── Post-meeting ────────────────────────────────────────────────────────────
    async def summarize(
        self,
        *,
        meeting: dict,
        intents: list[dict],
        suggestions: list[dict],
        crm: dict,
        transcript: str,
        history: list[dict] | None = None,
        docs: list[dict] | None = None,
        persona: str = "sales",
        comms: list[dict] | None = None,
        profile_context: str = "",
    ) -> dict:
        """Generate the post-meeting summary + follow-up artifacts, synthesizing the current
        transcript with prior meetings (`history`), account sources (`crm`, `docs`), and the
        owner's live Gmail/Drive/Slack content (`comms`).
        `persona` ('tech'|'sales') frames the brief for the owner's team."""
        raise NotImplementedError
