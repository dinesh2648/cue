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
import os
import re
import tempfile

from ..config import settings
from ..integrations import gmail as gmail_api
from ..integrations import google_drive as drive_api
from ..integrations import hubspot
from ..integrations import notion as notion_api
from ..integrations import slack as slack_api
from ..knowledge.store import index

log = logging.getLogger("copilot.claude_sdk")

# Stable working directory for the Agent SDK subprocess. Lives under the system temp
# dir (always present) and is (re)created before each run so an ephemeral cleanup
# mid-session can't break the agent — a hardcoded path once did exactly that.
_SCRATCH = os.path.join(tempfile.gettempdir(), "cue-agent-sdk")

_SYSTEM = (
    "You are a real-time meeting copilot. When the other person asks something, find the answer and "
    "reply with a SHORT, direct response the user can say out loud.\n"
    "Sources: use the CRM/docs tools (get_account_context, list_open_tickets, search_enterprise_docs) "
    "for anything about the customer account, contract, support, security, pricing or product; use "
    "WebSearch (and WebFetch) for general research or current facts not in those tools.\n"
    "Style — strict:\n"
    "- One sentence when possible; two short sentences MAX; never exceed ~45 words. Be blunt.\n"
    "- No headings, bullet lists, emojis, preamble ('Here's…'), or meta-commentary "
    "('not in our CRM'). Inline **bold** for one key figure/term is fine; no other markdown.\n"
    "- NEVER append a 'Sources'/'Citations' section or paste URLs — sources are shown separately.\n"
    "Ground every claim in tool/web results — never invent. Always use at least one tool first. "
    "If nothing is found, say in one line that you'll confirm and follow up."
)

_SYSTEM_TECH = (
    "You are a real-time ENGINEERING meeting copilot for a tech lead / engineer. When someone asks "
    "something, find the answer and reply SHORT and direct.\n"
    "Sources: use the connected tools — Jira for tickets/sprints/work items, GitHub for repos/PRs/"
    "code, Notion/Drive/docs for design & runbooks, WebSearch for anything external or current. "
    "Do NOT use CRM or LinkedIn — this is an engineering context. Capture requirements crisply.\n"
    "Style — strict: max 2 short sentences (~45 words); no headings, bullet lists, emojis, preamble "
    "or meta-commentary; inline **bold** for one key term is fine; never paste a sources list. "
    "Ground every claim in tool/web results — never invent. Use at least one tool first; if nothing "
    "is found, say in one line you'll confirm and follow up."
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


async def run_turn(
    query: str, intent_type: str, company_id: str | None,
    servers: list[dict] | None = None, persona: str = "sales",
    drive_token: str | None = None, gmail_token: str | None = None, slack_token: str | None = None,
) -> dict | None:
    if not available():
        return None
    # Tech persona never touches LinkedIn (engineering context).
    if persona == "tech":
        servers = [s for s in (servers or []) if s.get("name") != "linkedin"]
    try:
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            ResultMessage,
            TextBlock,
            ToolUseBlock,
            create_sdk_mcp_server,
            tool,
        )
        from claude_agent_sdk import query as run_query  # aliased: `query` is our param
    except ImportError:
        return None

    sources: list[dict] = []
    evidence: list[str] = []
    used_tools: list[str] = []
    used_user: set[str] = set()

    # Notion via a static PAT is read in-process (its hosted MCP rejects PATs). A DCR OAuth
    # connection (inprocess=False) instead flows through the hosted Notion MCP as a remote server.
    notion_token = next(
        (s.get("token") for s in (servers or [])
         if s.get("name") == "notion" and s.get("inprocess")
         and s.get("token") and not str(s["token"]).startswith("demo-")),
        None,
    )

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

    # In-process Notion tools (read the user's real Notion via the Notion API + their token).
    notion_tools = []
    if notion_token:
        @tool("search_notion", "Search the signed-in user's Notion workspace for pages/databases by keyword.", {"query": str})
        async def search_notion(args: dict) -> dict:
            used_user.add("notion")
            used_tools.append("notion")
            try:
                hits = await notion_api.search(notion_token, args.get("query", ""), k=6)
            except Exception as exc:
                return {"content": [{"type": "text", "text": f"Notion search failed: {exc}"}]}
            for h in hits[:6]:
                sources.append({"label": f"Notion · {h['title'][:48]}", "type": "connector", "detail": "your Notion", "url": h.get("url", "")})
                evidence.append(f"Notion: {h['title']}")
            return {"content": [{"type": "text", "text": json.dumps(hits)[:3000]}]}

        @tool("read_notion_page", "Read the text content of a Notion page by its id (from search_notion).", {"page_id": str})
        async def read_notion_page(args: dict) -> dict:
            used_user.add("notion")
            used_tools.append("notion")
            try:
                txt = await notion_api.page_text(notion_token, args.get("page_id", ""))
            except Exception as exc:
                return {"content": [{"type": "text", "text": f"Notion read failed: {exc}"}]}
            return {"content": [{"type": "text", "text": txt or "(empty page)"}]}

        notion_tools = [search_notion, read_notion_page]

    # In-process Google Drive tools (no hosted MCP for Drive — read via the API + user token).
    drive_tools = []
    if drive_token:
        @tool("search_drive", "Full-text search the signed-in user's Google Drive for relevant docs.", {"query": str})
        async def search_drive(args: dict) -> dict:
            used_user.add("google_drive")
            used_tools.append("google_drive")
            try:
                hits = await drive_api.search(drive_token, args.get("query", ""), k=6)
            except Exception as exc:
                return {"content": [{"type": "text", "text": f"Drive search failed: {exc}"}]}
            for h in hits[:6]:
                sources.append({"label": f"Drive · {h['name'][:48]}", "type": "connector", "detail": "your Drive", "url": h.get("url", "")})
            return {"content": [{"type": "text", "text": json.dumps(hits)[:3000]}]}

        @tool("read_drive_file", "Read a Google Drive file's text by its id (from search_drive).", {"file_id": str})
        async def read_drive_file(args: dict) -> dict:
            used_user.add("google_drive")
            used_tools.append("google_drive")
            try:
                txt = await drive_api.read_file(drive_token, args.get("file_id", ""))
            except Exception as exc:
                return {"content": [{"type": "text", "text": f"Drive read failed: {exc}"}]}
            return {"content": [{"type": "text", "text": txt or "(empty file)"}]}

        drive_tools = [search_drive, read_drive_file]

    # In-process Gmail tools (no hosted MCP for Gmail — read via the API + user token).
    gmail_tools = []
    if gmail_token:
        @tool("search_gmail", "Search the signed-in user's Gmail (Gmail query syntax, e.g. from:acme.com).", {"query": str})
        async def search_gmail(args: dict) -> dict:
            used_user.add("gmail")
            used_tools.append("gmail")
            try:
                hits = await gmail_api.search(gmail_token, args.get("query", ""), k=8)
            except Exception as exc:
                return {"content": [{"type": "text", "text": f"Gmail search failed: {exc}"}]}
            for h in hits[:8]:
                sources.append({"label": f"Email · {(h.get('subject') or '(no subject)')[:48]}", "type": "connector", "detail": "your Gmail", "url": ""})
            return {"content": [{"type": "text", "text": json.dumps(hits)[:3000]}]}

        @tool("read_email", "Read a Gmail message's text by its id (from search_gmail).", {"message_id": str})
        async def read_email(args: dict) -> dict:
            used_user.add("gmail")
            used_tools.append("gmail")
            try:
                txt = await gmail_api.read_message(gmail_token, args.get("message_id", ""))
            except Exception as exc:
                return {"content": [{"type": "text", "text": f"Gmail read failed: {exc}"}]}
            return {"content": [{"type": "text", "text": txt or "(empty message)"}]}

        gmail_tools = [search_gmail, read_email]

    # In-process Slack tools (no hosted MCP — read via the Slack Web API + user token).
    slack_tools = []
    if slack_token:
        @tool("search_slack", "Search the signed-in user's Slack messages for a topic/customer.", {"query": str})
        async def search_slack(args: dict) -> dict:
            used_user.add("slack")
            used_tools.append("slack")
            try:
                hits = await slack_api.search(slack_token, args.get("query", ""), k=8)
            except Exception as exc:
                return {"content": [{"type": "text", "text": f"Slack search failed: {exc}"}]}
            for h in hits[:6]:
                sources.append({"label": f"Slack · #{h.get('channel', '')}", "type": "connector", "detail": "your Slack", "url": h.get("permalink", "")})
            return {"content": [{"type": "text", "text": json.dumps(hits)[:3000]}]}

        @tool("read_slack_channel", "Read recent messages in a Slack channel by name (e.g. 'engineering').", {"channel": str})
        async def read_slack_channel(args: dict) -> dict:
            used_user.add("slack")
            used_tools.append("slack")
            try:
                cid = await slack_api.find_channel(slack_token, args.get("channel", ""))
                msgs = await slack_api.channel_history(slack_token, cid) if cid else []
            except Exception as exc:
                return {"content": [{"type": "text", "text": f"Slack read failed: {exc}"}]}
            return {"content": [{"type": "text", "text": json.dumps(msgs)[:3000] or "(no messages)"}]}

        slack_tools = [search_slack, read_slack_channel]

    os.makedirs(_SCRATCH, exist_ok=True)  # survive ephemeral cleanup mid-session
    server = create_sdk_mcp_server(
        "copilot",
        tools=[get_account_context, list_open_tickets, search_enterprise_docs, *notion_tools, *drive_tools, *gmail_tools, *slack_tools],
    )
    mcp_servers: dict = {"copilot": server}
    allowed = [
        "mcp__copilot__get_account_context",
        "mcp__copilot__list_open_tickets",
        "mcp__copilot__search_enterprise_docs",
        "WebSearch",
        "WebFetch",
    ]
    if notion_token:
        allowed += ["mcp__copilot__search_notion", "mcp__copilot__read_notion_page"]
    if drive_token:
        allowed += ["mcp__copilot__search_drive", "mcp__copilot__read_drive_file"]
    if gmail_token:
        allowed += ["mcp__copilot__search_gmail", "mcp__copilot__read_email"]
    if slack_token:
        allowed += ["mcp__copilot__search_slack", "mcp__copilot__read_slack_channel"]

    # Attach the owner's connected REMOTE MCP servers (HubSpot, …) with their OAuth token.
    # Skip in-process sources (PAT-Notion handled above); everything else is a remote MCP server.
    user_servers: set[str] = set()
    for s in servers or []:
        name, url, token = s.get("name"), s.get("url"), s.get("token")
        if not (name and url) or s.get("inprocess"):
            continue
        if token and token.startswith("demo-"):
            continue  # placeholder demo connection — not a real credential
        # SSE servers (e.g. Atlassian/Jira) use the SSE config shape (no "type"); others HTTP.
        cfg: dict = {"url": url} if s.get("transport") == "sse" else {"type": "http", "url": url}
        if token:
            cfg["headers"] = {"Authorization": f"Bearer {token}"}
        mcp_servers[name] = cfg
        allowed.append(f"mcp__{name}")  # allow all tools from this server
        user_servers.add(name)

    options = ClaudeAgentOptions(
        mcp_servers=mcp_servers,
        allowed_tools=allowed,
        system_prompt=_SYSTEM_TECH if persona == "tech" else _SYSTEM,
        permission_mode="bypassPermissions",
        setting_sources=[],
        max_turns=8 if (user_servers or notion_token or drive_token or gmail_token or slack_token) else 6,
        cwd=_SCRATCH,
    )

    prompt = (
        f'The other person asked: "{query}" (topic: {intent_type}). '
        "If it's about our customer account, contract, support, security, pricing or product, use the "
        "CRM/docs tools. Otherwise — company/market/person research or any current fact — research it "
        "live with WebSearch (and WebFetch). Then give me the short answer."
    )

    answer_parts: list[str] = []
    used_web = False
    try:
        async for msg in run_query(prompt=prompt, options=options):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        answer_parts.append(block.text)
                    elif isinstance(block, ToolUseBlock):
                        name = (getattr(block, "name", "") or "").lower()
                        if "websearch" in name or "webfetch" in name:
                            used_web = True
                        else:
                            for sn in user_servers:
                                if name.startswith(f"mcp__{sn.lower()}"):
                                    used_user.add(sn)
            elif isinstance(msg, ResultMessage):
                if not answer_parts and getattr(msg, "result", None):
                    answer_parts.append(msg.result)
    except Exception as exc:
        log.warning("Claude Agent SDK run failed; falling back: %s", exc)
        return None

    answer = " ".join(p.strip() for p in answer_parts if p.strip())
    if not answer:
        return None

    # Surface the user's own connected tools as sources (live, permission-scoped).
    # Notion already added specific page sources from its tool, so skip the generic chip.
    for sn in used_user:
        if sn == "notion":
            continue
        sources.append({
            "label": f"{sn.replace('_', ' ').title()} (your account)",
            "type": "connector", "detail": "live · your access", "url": "",
        })
        used_tools.append("user")

    # If Claude researched the web, surface it as a source — plus any URLs it cited
    # (captured from the full answer BEFORE we strip any trailing "Sources" block).
    if used_web:
        sources.append({"label": "Web research", "type": "document", "detail": "live web", "url": ""})
        used_tools.append("web")
        for url in dict.fromkeys(re.findall(r"https?://[^\s)>\]\"]+", answer)):
            host = url.split("//", 1)[-1].split("/", 1)[0]
            sources.append({"label": host[:60], "type": "document", "detail": "web", "url": url})

    # The model often tacks on a "Sources:" / "Citations:" block despite instructions —
    # strip it so the spoken answer stays short and straight (sources show separately).
    answer = re.split(
        r"\n+\s*\**\s*(?:sources?|citations?|references?)\b.*",
        answer, maxsplit=1, flags=re.IGNORECASE | re.DOTALL,
    )[0].strip()

    # dedupe sources preserving order
    seen, uniq = set(), []
    for s in sources:
        key = (s["label"], s["type"], s.get("url", ""))
        if key not in seen:
            seen.add(key)
            uniq.append(s)

    grounded = bool(used_tools)
    confidence = 0.93 if (used_tools and (evidence or used_web or used_user)) else 0.75
    # Scope priority: the user's own connected data > live web > seeded demo.
    access_scope = "user" if used_user else "web" if used_web else "demo"
    return {
        "answer": answer,
        "evidence": evidence[:5],
        "sources": uniq,
        "confidence": round(confidence, 2),
        "engine": "claude+mcp",
        "grounded": grounded,
        "access_scope": access_scope,
    }
