"""Claude Agent SDK runtime with an in-process MCP server.

This is the *local* live path: the Claude Agent SDK runs the agent loop through the
authenticated `claude` CLI (no API key needed) and connects to an in-process MCP
server whose tools expose the copilot's data layer. Claude genuinely calls the MCP
tools to answer the customer's question.

In production these same tools proxy to each employee's *remote* provider MCP using
their OAuth token (live-federated, permission-scoped). For the demo they read the
seeded CRM + knowledge so a real Claude+MCP run works with zero external setup.
"""
from __future__ import annotations

import json
import logging

from ..config import settings
from ..integrations import hubspot
from ..knowledge.store import index

log = logging.getLogger("copilot.claude_sdk")

_SCRATCH = (
    "/private/tmp/claude-501/-Users-kandakatladinesh-Documents-Personal-AISalesAgent/"
    "18adc70d-da80-43d0-be62-b374ae332904/scratchpad"
)

_SYSTEM = (
    "You are a virtual Sales Engineer assisting a sales rep live during a customer call. "
    "The customer just asked a question. Use the available tools (get_account_context, "
    "search_enterprise_docs, list_open_tickets) to find the facts, then reply with the exact words "
    "the rep should say — concise (2-4 sentences), warm, and speakable immediately. Output ONLY "
    "those words: no preamble like 'Here's what you can say', no surrounding quotes, no asides or "
    "parentheticals. Use only what the tools return — never invent specifics. Always call at least "
    "one tool before answering. If the tools don't contain the answer, say you'll confirm and "
    "follow up — never guess."
)


def available() -> bool:
    if not settings.use_agent_sdk:
        return False
    try:
        import claude_agent_sdk  # noqa: F401
        import shutil

        return shutil.which("claude") is not None
    except ImportError:
        return False


async def run_turn(query: str, intent_type: str, company_id: str | None) -> dict | None:
    if not available():
        return None
    try:
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            ResultMessage,
            TextBlock,
            ToolUseBlock,
            create_sdk_mcp_server,
            query,
            tool,
        )
    except ImportError:
        return None

    sources: list[dict] = []
    evidence: list[str] = []
    used_tools: list[str] = []

    @tool("get_account_context", "Get the customer's CRM account snapshot: company, deal, stage, contract status.", {})
    async def get_account_context(_args: dict) -> dict:
        used_tools.append("crm")
        from ..db import SessionLocal

        db = SessionLocal()
        try:
            ctx = hubspot.company_context(db, company_id)
        finally:
            db.close()
        deal = (ctx.get("deals") or [{}])[0]
        sources.append({"label": "HubSpot CRM", "type": "crm", "detail": "live", "url": ""})
        for k in ("dealstage", "contract_status", "amount", "closedate", "go_live_date", "renewal_date"):
            if deal.get(k):
                evidence.append(f"{k}: {deal[k]}")
        return {"content": [{"type": "text", "text": json.dumps(ctx)[:3000]}]}

    @tool("list_open_tickets", "List the customer's open support tickets.", {})
    async def list_open_tickets(_args: dict) -> dict:
        used_tools.append("tickets")
        from ..db import SessionLocal

        db = SessionLocal()
        try:
            ctx = hubspot.company_context(db, company_id)
        finally:
            db.close()
        open_t = [t for t in ctx.get("tickets", []) if str(t.get("status", "")).lower() != "closed"]
        sources.append({"label": "HubSpot CRM — tickets", "type": "crm", "detail": "live", "url": ""})
        for t in open_t:
            evidence.append(f"{t.get('id')}: {t.get('subject')} ({t.get('priority')}/{t.get('status')})")
        return {"content": [{"type": "text", "text": json.dumps(open_t)}]}

    @tool("search_enterprise_docs", "Search enterprise documents (proposals, security, contracts).", {"query": str})
    async def search_enterprise_docs(args: dict) -> dict:
        used_tools.append("docs")
        hits = await index.search(args.get("query", query), k=3)
        for h in hits:
            sources.append({"label": h.title, "type": "document", "detail": h.doc_type, "url": h.url})
            evidence.append(f"{h.title}: {h.snippet[:140]}")
        payload = [{"title": h.title, "snippet": h.snippet} for h in hits]
        return {"content": [{"type": "text", "text": json.dumps(payload)}]}

    server = create_sdk_mcp_server(
        "copilot",
        tools=[get_account_context, list_open_tickets, search_enterprise_docs],
    )
    options = ClaudeAgentOptions(
        mcp_servers={"copilot": server},
        allowed_tools=[
            "mcp__copilot__get_account_context",
            "mcp__copilot__list_open_tickets",
            "mcp__copilot__search_enterprise_docs",
        ],
        system_prompt=_SYSTEM,
        permission_mode="bypassPermissions",
        setting_sources=[],
        max_turns=6,
        cwd=_SCRATCH,
    )

    prompt = (
        f'The customer asked: "{query}" (detected topic: {intent_type}). '
        f"Find the answer with the tools and give me the response I should say."
    )

    answer_parts: list[str] = []
    try:
        async for msg in query(prompt=prompt, options=options):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        answer_parts.append(block.text)
            elif isinstance(msg, ResultMessage):
                if not answer_parts and getattr(msg, "result", None):
                    answer_parts.append(msg.result)
    except Exception as exc:
        log.warning("Claude Agent SDK run failed; falling back: %s", exc)
        return None

    answer = " ".join(p.strip() for p in answer_parts if p.strip())
    if not answer:
        return None

    # dedupe sources preserving order
    seen, uniq = set(), []
    for s in sources:
        key = (s["label"], s["type"])
        if key not in seen:
            seen.add(key)
            uniq.append(s)

    confidence = 0.93 if (used_tools and evidence) else 0.75
    return {
        "answer": answer,
        "evidence": evidence[:5],
        "sources": uniq,
        "confidence": round(confidence, 2),
        "engine": "claude+mcp",
        "grounded": bool(used_tools),
        "access_scope": "demo",  # in-process tools over seeded data (local dev)
    }
