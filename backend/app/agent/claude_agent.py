"""Claude agent runtime (live-federated, per-user MCP).

Runs Claude's agentic tool-use loop over the employee's *own* connected MCP servers
via Anthropic's native MCP connector. Because each server carries that user's OAuth
token, every fetch is permission-scoped by the source system — Claude can only read
what the employee can read.

Engine = "messages_mcp": Anthropic Messages API with `mcp_servers` (subprocess-free,
horizontally scalable). A Claude Agent SDK adapter can sit behind the same interface.
Returns None when no Anthropic key is configured so callers use the offline composer.
"""
from __future__ import annotations

import logging

from ..config import settings

log = logging.getLogger("copilot.claude")

_MCP_BETA = "mcp-client-2025-04-04"

_PROVIDER_LABEL = {
    "hubspot": ("HubSpot CRM", "crm"),
    "google_drive": ("Google Drive", "document"),
    "gmail": ("Gmail", "email"),
    "notion": ("Notion", "document"),
    "github": ("GitHub", "connector"),
    "jira": ("Jira", "connector"),
    "slack": ("Slack", "connector"),
}

_SYSTEM_SALES = (
    "You are a virtual Sales Engineer assisting a sales rep live during a customer call. "
    "A customer just asked a question. Use the connected tools to "
    "find the facts and answer it. The tools already enforce the rep's own access — only use "
    "what they return; never invent specifics. Reply with a concise, warm, ready-to-say response "
    "(2-4 sentences) the rep can speak immediately. If you cannot find the answer, say what you'd "
    "check next. Do not include citations inline — they are tracked separately."
)

_SYSTEM_TECH = (
    "You are a technical copilot assisting an engineer live during a working session or technical "
    "meeting. Someone just asked a question. Use the connected tools to find the facts — code, "
    "pull requests, issues, tickets, docs, threads — and answer it. Reach for GitHub for code/PRs/"
    "repos and Jira for tickets/sprints whenever the question touches them. The tools enforce the "
    "user's own access — only use what they return; never invent specifics. Reply with a concise, "
    "precise, ready-to-say response (2-4 sentences). If you cannot find the answer, say what you'd "
    "check next. Do not include citations inline — they are tracked separately."
)


def _system(persona: str) -> str:
    return _SYSTEM_TECH if persona == "tech" else _SYSTEM_SALES


def available() -> bool:
    return bool(settings.anthropic_api_key) and settings.resolved_agent_engine == "messages_mcp"


async def run_turn(
    query: str,
    intent_type: str,
    mcp_servers: list[dict],
    persona: str = "sales",
    context: str = "",
) -> dict | None:
    """Answer one question using the user's live MCP tools. None on fallback."""
    if not available():
        return None

    try:
        from anthropic import AsyncAnthropic
    except ImportError:  # pragma: no cover
        return None

    servers_payload = [
        {"type": "url", "url": s["url"], "name": s["name"], "authorization_token": s["token"]}
        for s in mcp_servers
    ]
    connected = ", ".join(sorted({s.get("name", "") for s in mcp_servers if s.get("name")}))

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    who = "person" if persona == "tech" else "customer"
    parts: list[str] = []
    if context:
        parts.append(
            "Recent conversation (resolve references like 'that' / 'it' / 'the last one' against "
            f"it, then answer the REAL question):\n{context}"
        )
    parts.append(f'The {who} asked: "{query}"')
    if connected:
        parts.append(
            f"You have live, permission-scoped access to these connected tools: {connected}. "
            "Call whichever are relevant — don't answer from memory when a tool can confirm."
        )
    parts.append(
        f"(Detected topic: {intent_type}.) Find the answer using the connected tools and "
        "give me the response to say."
    )
    user_msg = "\n\n".join(parts)

    try:
        kwargs: dict = {
            "model": settings.anthropic_model,
            "max_tokens": 600,
            "system": _system(persona),
            "messages": [{"role": "user", "content": user_msg}],
        }
        if servers_payload:
            kwargs["mcp_servers"] = servers_payload
            kwargs["betas"] = [_MCP_BETA]
            resp = await client.beta.messages.create(**kwargs)
        else:
            resp = await client.messages.create(**kwargs)
    except Exception as exc:
        log.warning("Claude agent call failed; falling back: %s", exc)
        return None

    return _parse(resp, mcp_servers)


def _parse(resp, mcp_servers: list[dict]) -> dict:
    answer_parts: list[str] = []
    used_providers: list[str] = []
    evidence: list[str] = []
    errors: list[str] = []

    for block in resp.content:
        btype = getattr(block, "type", "")
        if btype == "text":
            answer_parts.append(block.text)
        elif btype == "mcp_tool_use":
            provider = getattr(block, "server_name", "") or getattr(block, "name", "")
            if provider and provider not in used_providers:
                used_providers.append(provider)
        elif btype == "mcp_tool_result":
            if getattr(block, "is_error", False):
                errors.append(f"{getattr(block, 'server_name', '?')}: {_result_text(block)[:300]}")
                continue
            snippet = _result_text(block)
            if snippet:
                evidence.append(snippet[:200])

    # Diagnostics: which servers were offered, which Claude actually called, and any tool errors
    # (e.g. a connector rejecting the token) — otherwise "connected but no data" is invisible.
    if errors:
        log.warning("MCP tool errors during answer: %s", " | ".join(errors))
    log.info(
        "live answer: offered=[%s] used=%s evidence=%d",
        ", ".join(s.get("name", "") for s in mcp_servers), used_providers, len(evidence),
    )

    sources = []
    for p in used_providers:
        label, stype = _PROVIDER_LABEL.get(p, (p.title(), "connector"))
        sources.append({"label": label, "type": stype, "detail": "live", "url": ""})

    answer = " ".join(t.strip() for t in answer_parts if t.strip()) or "Let me pull that up and get right back to you."
    # Confidence: grounded tool use + a produced answer → high; answer-only → moderate.
    confidence = 0.92 if (used_providers and evidence) else 0.78 if answer_parts else 0.5
    return {
        "answer": answer,
        "evidence": evidence[:4],
        "sources": sources,
        "confidence": round(confidence, 2),
        "engine": "claude+mcp",
        "grounded": bool(used_providers),
        "access_scope": "user",  # live retrieval through THIS rep's own connectors
    }


def _result_text(block) -> str:
    content = getattr(block, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            text = getattr(item, "text", None) or (item.get("text") if isinstance(item, dict) else None)
            if text:
                parts.append(text)
        return " ".join(parts)
    return ""
