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
        """Classify a customer utterance into this pack's intent taxonomy."""
        raise NotImplementedError

    # ── Capability ────────────────────────────────────────────────────────────
    def has_deep(self, servers: list[dict]) -> bool:
        """Whether a deep (agentic) second tier will run for this turn."""
        return False

    # ── Inline flow (real-time, two-tier) ──────────────────────────────────────
    async def fast_answer(
        self, *, db, meeting, text: str, intent: IntentResult, doc_catalog: list[dict]
    ) -> dict:
        """Tier 1: instant grounded answer. Returns {answer, evidence, sources, confidence, actions}."""
        raise NotImplementedError

    async def deep_answer(
        self, *, db, meeting, text: str, intent: IntentResult, servers: list[dict]
    ) -> dict | None:
        """Tier 2: richer agentic answer that upgrades the card in place (or None to skip)."""
        return None

    # ── Post-meeting ────────────────────────────────────────────────────────────
    async def summarize(
        self, *, meeting: dict, intents: list[dict], suggestions: list[dict], crm: dict, transcript: str
    ) -> dict:
        """Generate the post-meeting summary + follow-up artifacts for this pack."""
        raise NotImplementedError
