"""Layer 1 — LLM triage.

Ask Claude (a fast, cheap model) whether the latest utterance actually needs a live
copilot answer, and if so what kind + a standalone query (pronouns resolved from recent
context). This is smarter than keyword matching: it distinguishes real questions/requests
from statements, opinions, acknowledgements and small talk using the conversation context.

Returns None when no Anthropic key is configured or the call fails, so callers fall back
to the deterministic regex detector (intent.detect_intent). Layer 2 (the deep answerer:
agent/claude_sdk.py / claude_agent.py) then runs only when triage says an answer is needed.
"""
from __future__ import annotations

import logging

import httpx

from ..config import settings
from .intent import IntentResult, family_for

log = logging.getLogger("copilot.triage")

_TIMEOUT = httpx.Timeout(8.0, connect=4.0)

_SYSTEM = (
    "You are the routing layer of a live meeting copilot. Given the recent transcript and the "
    "latest thing the OTHER PERSON (not the rep) said, decide whether it needs a real answer the "
    "rep should give right now.\n"
    "needs_answer = true ONLY for a genuine question or an explicit request for information or "
    "action that the rep must actually answer with facts. needs_answer = false for statements, "
    "opinions, acknowledgements ('sounds good'), greetings, small talk, and thinking-out-loud — "
    "and CRUCIALLY false for social pleasantries and well-wishes EVEN when phrased as a question, "
    "e.g. 'hope you're doing well?', 'hope all is okay?', 'how was your weekend?', 'how are you?', "
    "'hope you had a good break?'. These are rapport, not information requests — do not answer them.\n"
    "When true, write 'query' as a concise standalone question — resolve pronouns like 'it/they/"
    "that' from the context — and pick the best intent_type. Always call the classify_turn tool."
)


def _tool(labels: dict[str, str]) -> dict:
    return {
        "name": "classify_turn",
        "description": "Classify the latest utterance for a live meeting copilot.",
        "input_schema": {
            "type": "object",
            "properties": {
                "needs_answer": {
                    "type": "boolean",
                    "description": "True only if the other person asked a question or requested info/action.",
                },
                "intent_type": {
                    "type": "string",
                    "enum": list(labels.keys()),
                    "description": "; ".join(f"{k} = {v}" for k, v in labels.items()),
                },
                "query": {
                    "type": "string",
                    "description": "Concise standalone question to answer (pronouns resolved). Empty if needs_answer is false.",
                },
                "reason": {"type": "string", "description": "Brief justification."},
            },
            "required": ["needs_answer", "intent_type", "query", "reason"],
        },
    }


async def classify(text: str, recent: list[str] | None, labels: dict[str, str]) -> IntentResult | None:
    """Triage one utterance. Returns an IntentResult (actionable iff needs_answer) or None."""
    if not settings.anthropic_api_key:
        return None
    # Trivial asides ("ok", "yeah thanks") never need an answer — skip the API call.
    if len(text.split()) < 3:
        return IntentResult("general", "general", 0.1, text.strip())

    labels = labels or {"general": "any genuine question the rep should answer"}
    context = "\n".join(recent[-6:]) if recent else "(start of call)"
    user = (
        f"Recent transcript:\n{context}\n\n"
        f'Latest (other person): "{text}"\n\nClassify it with classify_turn.'
    )

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": settings.anthropic_api_key or "",
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": settings.triage_model,
                    "max_tokens": 300,
                    "system": _SYSTEM,
                    "tools": [_tool(labels)],
                    "tool_choice": {"type": "tool", "name": "classify_turn"},
                    "messages": [{"role": "user", "content": user}],
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # network / API error → regex fallback
        log.warning("triage failed; falling back to regex: %s", exc)
        return None

    inp = next(
        (b.get("input") for b in data.get("content", [])
         if b.get("type") == "tool_use" and b.get("name") == "classify_turn"),
        None,
    )
    if not isinstance(inp, dict):
        return None

    needs = bool(inp.get("needs_answer"))
    intent_type = inp.get("intent_type") or "general"
    if intent_type not in labels:
        intent_type = "general"
    query = (inp.get("query") or "").strip() or text.strip()
    log.info("triage: needs=%s intent=%s | %s", needs, intent_type, (inp.get("reason") or "")[:80])
    return IntentResult(intent_type, family_for(intent_type), 0.85 if needs else 0.1, query)
