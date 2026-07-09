"""Advisory Agent — turns meeting context + retrieved knowledge + profile into a grounded response.

Two responsibilities:
- respond(): the answer itself, produced over the user's live tools (messages_mcp) with the meeting
  state + in-process sources + advisory preamble all in context.
- envelope(): the structured tail the spec asks for — Assumptions, Risks, Recommended next actions —
  derived from the answer + its evidence (a fast, tool-less pass). Grounded only; never invents.
"""
from __future__ import annotations

import json
import logging

from ..agent import claude_agent
from ..integrations.llm import llm_complete
from .retrieval import Retrieval

log = logging.getLogger("copilot.advisory")


async def respond(query: str, intent_type: str, persona: str, r: Retrieval, context: str) -> dict | None:
    """Grounded answer over the role-scoped tools + injected context. None to fall back."""
    full_ctx = f"{r.meeting_state}\n\n{context}".strip() if r.meeting_state else context
    return await claude_agent.run_turn(
        query, intent_type, r.servers, persona=persona, context=full_ctx,
        comms=r.comms, profile_context=r.preamble,
    )


_ENVELOPE_SYS = (
    "You review an AI advisor's draft answer for a professional. Return JSON ONLY with keys:\n"
    "- assumptions: array of any assumptions the answer relies on (<=3). [] if none.\n"
    "- risks: array of caveats, uncertainties or risks the person should know (<=3). [] if none.\n"
    "- next_actions: array of concrete recommended next steps for the person (<=3). [] if none.\n"
    "Ground strictly in the answer and its evidence — never invent facts, numbers or names. "
    "Keep each item one short phrase. JSON only."
)


async def envelope(query: str, answer: str, evidence: list[str]) -> dict:
    """Assumptions / risks / next actions for an answer. Best-effort — {} on any failure."""
    if not answer:
        return {"assumptions": [], "risks": [], "next_actions": []}
    ev = "\n".join(f"- {e}" for e in (evidence or [])[:6]) or "(none provided)"
    raw = await llm_complete(
        system=_ENVELOPE_SYS,
        user=f'Question: "{query}"\n\nDraft answer:\n{answer}\n\nEvidence:\n{ev}\n\nReturn the JSON envelope.',
        max_tokens=350,
        temperature=0.2,
        timeout=15.0,
    )
    if not raw:
        return {"assumptions": [], "risks": [], "next_actions": []}
    try:
        data = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
    except (ValueError, json.JSONDecodeError):
        return {"assumptions": [], "risks": [], "next_actions": []}

    def _clean(v) -> list[str]:
        return [str(x).strip()[:160] for x in v if str(x).strip()][:3] if isinstance(v, list) else []

    return {
        "assumptions": _clean(data.get("assumptions")),
        "risks": _clean(data.get("risks")),
        "next_actions": _clean(data.get("next_actions")),
    }
