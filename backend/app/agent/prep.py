"""Pre-meeting preparation agent.

Given an upcoming calendar event + the internal context we already have (prior meeting
notes, CRM snapshot, enterprise docs), run a Claude agent that ALSO researches the rep's
live connected sources — HubSpot, Notion, Google Drive, Gmail — and the public web, then
writes a structured preparation brief (markdown).

Self-contained on purpose: it does NOT reuse the live-suggestion `run_turn` (which is hard
-tuned to 2-sentence answers for the SLA path). Falls back to a plain LLM compose, and then
to a deterministic brief, so it always returns something useful.
"""
from __future__ import annotations

import json
import logging
import os

from ..integrations import gmail as gmail_api
from ..integrations import google_drive as drive_api
from ..integrations import notion as notion_api
from ..integrations import slack as slack_api
from ..integrations.llm import llm_complete

log = logging.getLogger("copilot.prep")

_SCRATCH = os.path.join(os.path.sep, "tmp", "cue-agent-prep")

_SECTIONS = (
    "Write GitHub-flavored markdown with EXACTLY these sections, in order, omitting a section "
    "only if you truly have nothing for it:\n"
    "## TL;DR  — 2-3 bullets: who, why this meeting, the one thing to get right.\n"
    "## Where we left off  — open items / decisions / promises from prior meetings & emails.\n"
    "## Account snapshot  — deal stage, value, open tickets, sentiment (from CRM).\n"
    "## Who's in the room  — each external attendee: name, likely role, any prior interaction.\n"
    "## Talking points  — 3-5 specific things to raise, tied to their context.\n"
    "## Risks & watch-outs  — objections, blockers, anything sensitive.\n"
    "Be concrete and concise. Bullets over paragraphs. No preamble, no sign-off."
)

# Tool-using prompt (agent path): research LIVE across connected sources + web.
_SYSTEM_AGENT = (
    "You are a meeting-prep researcher for a {persona}. You produce a tight, skimmable "
    "preparation brief the rep can read in 60 seconds before a customer call.\n"
    "Use the tools to research the customer LIVE: their CRM record (HubSpot — deals, tickets, "
    "owner, lifecycle), recent email threads (Gmail), relevant docs (Drive/Notion), and the "
    "public web (company news, the attendees' roles). Ground every claim in what you find; "
    "never invent specifics.\n" + _SECTIONS
)

# Compose-only prompt (no tools): synthesize STRICTLY from the context block provided.
_SYSTEM_COMPOSE = (
    "You are a meeting-prep assistant for a {persona}. Using ONLY the context provided below "
    "(prior meeting notes, CRM snapshot, internal docs, attendee list), write a tight, skimmable "
    "preparation brief the rep can read in 60 seconds.\n"
    "You have NO tools — do not call any, do not output function calls, and do not invent "
    "specifics not present in the context. If the context is thin, keep the brief short and note "
    "what to confirm live.\n" + _SECTIONS
)

_TECH_EXTRA = (
    " This is an engineering/technical meeting — favor Jira/GitHub/Drive context (open issues, "
    "PRs, design docs) and DO NOT use LinkedIn."
)


def _context_block(ctx: dict) -> str:
    """Render the internal context we gathered into a compact prompt block."""
    parts = [
        f"Event: {ctx.get('title', '')}",
        f"When: {ctx.get('start', '')}",
        f"Customer: {ctx.get('customer') or 'unknown'}",
        f"External attendees: {', '.join(ctx.get('external_attendees') or []) or 'none listed'}",
        f"Organizer: {ctx.get('organizer', '')}",
    ]
    crm = ctx.get("crm") or {}
    if crm.get("company"):
        parts.append("CRM (HubSpot) snapshot:\n" + json.dumps(crm)[:1500])
    history = ctx.get("history") or []
    if history:
        parts.append("Prior meetings with this customer:\n" + json.dumps(history)[:2000])
    docs = ctx.get("docs") or []
    if docs:
        parts.append("Relevant internal docs:\n" + json.dumps(docs)[:1000])
    return "\n\n".join(parts)


async def _agent_brief(
    ctx: dict, persona: str, servers: list[dict],
    notion_token: str | None, drive_token: str | None, gmail_token: str | None,
    slack_token: str | None = None,
) -> dict | None:
    """Run the Claude Agent SDK with the user's connected sources + web. None on failure.

    Sources reach the agent two ways: providers with a hosted MCP (HubSpot, GitHub, Jira) as
    remote servers; providers without one (Notion, Google Drive, Gmail) as in-process tools
    that call their REST API with the user's token. Every CONNECTED source is wired in.
    """
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
        from claude_agent_sdk import query as run_query
    except Exception:  # not installed, or import-time CLI/version probe failed — fall back
        return None

    inproc_tools = []
    allowed_inproc: list[str] = []
    if notion_token:
        @tool("search_notion", "Search the user's Notion for pages about the customer/topic.", {"query": str})
        async def search_notion(args):  # noqa: ANN001
            try:
                hits = await notion_api.search(notion_token, args.get("query", ""), k=6)
            except Exception as exc:  # pragma: no cover
                return {"content": [{"type": "text", "text": f"Notion search failed: {exc}"}]}
            return {"content": [{"type": "text", "text": json.dumps(hits)[:3000]}]}

        @tool("read_notion_page", "Read a Notion page's text by id.", {"page_id": str})
        async def read_notion_page(args):  # noqa: ANN001
            try:
                txt = await notion_api.page_text(notion_token, args.get("page_id", ""))
            except Exception as exc:  # pragma: no cover
                return {"content": [{"type": "text", "text": f"Notion read failed: {exc}"}]}
            return {"content": [{"type": "text", "text": txt or "(empty page)"}]}

        inproc_tools += [search_notion, read_notion_page]
        allowed_inproc += ["mcp__prep__search_notion", "mcp__prep__read_notion_page"]

    if drive_token:
        @tool("search_drive", "Full-text search the user's Google Drive for relevant docs.", {"query": str})
        async def search_drive(args):  # noqa: ANN001
            try:
                hits = await drive_api.search(drive_token, args.get("query", ""), k=6)
            except Exception as exc:  # pragma: no cover
                return {"content": [{"type": "text", "text": f"Drive search failed: {exc}"}]}
            return {"content": [{"type": "text", "text": json.dumps(hits)[:3000]}]}

        @tool("read_drive_file", "Read a Google Drive file's text by id.", {"file_id": str})
        async def read_drive_file(args):  # noqa: ANN001
            try:
                txt = await drive_api.read_file(drive_token, args.get("file_id", ""))
            except Exception as exc:  # pragma: no cover
                return {"content": [{"type": "text", "text": f"Drive read failed: {exc}"}]}
            return {"content": [{"type": "text", "text": txt or "(empty file)"}]}

        inproc_tools += [search_drive, read_drive_file]
        allowed_inproc += ["mcp__prep__search_drive", "mcp__prep__read_drive_file"]

    if gmail_token:
        @tool("search_gmail", "Search the user's Gmail (Gmail query syntax, e.g. from:acme.com).", {"query": str})
        async def search_gmail(args):  # noqa: ANN001
            try:
                hits = await gmail_api.search(gmail_token, args.get("query", ""), k=8)
            except Exception as exc:  # pragma: no cover
                return {"content": [{"type": "text", "text": f"Gmail search failed: {exc}"}]}
            return {"content": [{"type": "text", "text": json.dumps(hits)[:3000]}]}

        @tool("read_email", "Read a Gmail message's text by id.", {"message_id": str})
        async def read_email(args):  # noqa: ANN001
            try:
                txt = await gmail_api.read_message(gmail_token, args.get("message_id", ""))
            except Exception as exc:  # pragma: no cover
                return {"content": [{"type": "text", "text": f"Gmail read failed: {exc}"}]}
            return {"content": [{"type": "text", "text": txt or "(empty message)"}]}

        inproc_tools += [search_gmail, read_email]
        allowed_inproc += ["mcp__prep__search_gmail", "mcp__prep__read_email"]

    if slack_token:
        @tool("search_slack", "Search the user's Slack messages for a topic/customer.", {"query": str})
        async def search_slack(args):  # noqa: ANN001
            try:
                hits = await slack_api.search(slack_token, args.get("query", ""), k=8)
            except Exception as exc:  # pragma: no cover
                return {"content": [{"type": "text", "text": f"Slack search failed: {exc}"}]}
            return {"content": [{"type": "text", "text": json.dumps(hits)[:3000]}]}

        @tool("read_slack_channel", "Read recent messages in a Slack channel by name (e.g. 'engineering').", {"channel": str})
        async def read_slack_channel(args):  # noqa: ANN001
            try:
                cid = await slack_api.find_channel(slack_token, args.get("channel", ""))
                msgs = await slack_api.channel_history(slack_token, cid) if cid else []
            except Exception as exc:  # pragma: no cover
                return {"content": [{"type": "text", "text": f"Slack read failed: {exc}"}]}
            return {"content": [{"type": "text", "text": json.dumps(msgs)[:3000] or "(no messages)"}]}

        inproc_tools += [search_slack, read_slack_channel]
        allowed_inproc += ["mcp__prep__search_slack", "mcp__prep__read_slack_channel"]

    os.makedirs(_SCRATCH, exist_ok=True)
    mcp_servers: dict = {}
    allowed = ["WebSearch", "WebFetch"]
    if inproc_tools:
        mcp_servers["prep"] = create_sdk_mcp_server("prep", tools=inproc_tools)
        allowed += allowed_inproc

    attached: set[str] = set()  # remote MCP servers wired in (hubspot, github, jira, …)
    for s in servers or []:
        name, url, token = s.get("name"), s.get("url"), s.get("token")
        if not (name and url) or name == "notion":
            continue
        if persona == "tech" and name == "linkedin":
            continue
        if token and token.startswith("demo-"):
            continue
        cfg: dict = {"url": url} if s.get("transport") == "sse" else {"type": "http", "url": url}
        if token:
            cfg["headers"] = {"Authorization": f"Bearer {token}"}
        mcp_servers[name] = cfg
        allowed.append(f"mcp__{name}")
        attached.add(name)

    system = _SYSTEM_AGENT.format(persona="sales engineer / AE" if persona != "tech" else "software engineer")
    if persona == "tech":
        system += _TECH_EXTRA

    options = ClaudeAgentOptions(
        mcp_servers=mcp_servers,
        allowed_tools=allowed,
        system_prompt=system,
        permission_mode="bypassPermissions",
        setting_sources=[],
        max_turns=12,
        cwd=_SCRATCH,
    )
    prompt = (
        "Prepare me for this upcoming meeting. Research the customer using my connected tools "
        "and the web, then write the brief.\n\n" + _context_block(ctx)
    )

    parts: list[str] = []
    used_web = False
    used: set[str] = set()  # source keys the agent actually invoked (for attribution)
    try:
        async for msg in run_query(prompt=prompt, options=options):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        parts.append(block.text)
                    elif isinstance(block, ToolUseBlock):
                        # Text emitted BEFORE a tool call is the model thinking out loud
                        # ("I'll research…"). The real brief is what it writes AFTER the last
                        # tool call, so drop pre-tool narration to keep the output clean.
                        parts.clear()
                        nm = (getattr(block, "name", "") or "").lower()
                        if "websearch" in nm or "webfetch" in nm:
                            used_web = True
                        elif nm.startswith("mcp__prep__"):  # in-process Notion/Drive/Gmail/Slack
                            if "notion" in nm:
                                used.add("notion")
                            elif "drive" in nm:
                                used.add("google_drive")
                            elif "gmail" in nm or "email" in nm:
                                used.add("gmail")
                            elif "slack" in nm:
                                used.add("slack")
                        else:
                            for sn in attached:  # remote MCP servers (hubspot, github, jira)
                                if nm.startswith(f"mcp__{sn.lower()}"):
                                    used.add(sn)
            elif isinstance(msg, ResultMessage):
                if not parts and getattr(msg, "result", None):
                    parts.append(msg.result)
    except Exception as exc:
        log.warning("prep agent failed; falling back: %s", exc)
        return None

    markdown = "\n".join(p.rstrip() for p in parts if p.strip()).strip()
    # Trim any remaining lead-in before the first markdown heading so the brief starts clean.
    if "## " in markdown:
        markdown = markdown[markdown.index("## "):]
    if not markdown:
        return None

    sources: list[dict] = []
    for sn in sorted(used):
        sources.append({"label": f"{sn.replace('_', ' ').title()} (your account)", "type": "connector", "detail": "live · your access", "url": ""})
    if used_web:
        sources.append({"label": "Web research", "type": "document", "detail": "live web", "url": ""})
    return {"markdown": markdown, "sources": sources, "engine": "claude+mcp"}


async def _llm_brief(ctx: dict, persona: str) -> dict | None:
    """No agent/connected tools — compose a brief STRICTLY from the internal context we have."""
    system = _SYSTEM_COMPOSE.format(persona="sales engineer / AE" if persona != "tech" else "software engineer")
    if persona == "tech":
        system += _TECH_EXTRA
    out = await llm_complete(system, _context_block(ctx), max_tokens=1200, temperature=0.3, timeout=60)
    if not out:
        return None
    return {"markdown": out.strip(), "sources": [{"label": "Prior meetings & CRM", "type": "document", "detail": "internal", "url": ""}], "engine": "llm"}


def _offline_brief(ctx: dict) -> dict:
    """Last resort — a deterministic brief from internal context (no LLM available)."""
    lines = [f"## {ctx.get('title') or 'Upcoming meeting'}", ""]
    if ctx.get("customer"):
        lines.append(f"**Customer:** {ctx['customer']}")
    ext = ctx.get("external_attendees") or []
    if ext:
        lines.append(f"**Attendees:** {', '.join(ext)}")
    history = ctx.get("history") or []
    if history:
        lines += ["", "## Where we left off"]
        for h in history[:5]:
            lines.append(f"- **{h.get('date', '')} — {h.get('title', '')}**: {(h.get('summary') or '')[:200]}")
            for a in (h.get("open_actions") or [])[:3]:
                lines.append(f"  - open: {a}")
    crm = (ctx.get("crm") or {}).get("company") or {}
    if crm:
        lines += ["", "## Account snapshot", f"- {json.dumps(crm)[:300]}"]
    if len(lines) <= 2:
        lines.append("_No prior context found. Connect HubSpot, Notion, Drive or Gmail for a researched brief._")
    return {"markdown": "\n".join(lines), "sources": [], "engine": "offline"}


async def generate_prep(
    ctx: dict, *, persona: str, servers: list[dict] | None,
    notion_token: str | None = None, drive_token: str | None = None, gmail_token: str | None = None,
    slack_token: str | None = None,
) -> dict:
    """Best brief we can produce: agent (live tools) → LLM compose → deterministic.

    Every tier is guarded — a failure in one degrades to the next, never to a 500. The
    offline brief (from the internal context we already gathered) is the guaranteed floor.
    """
    if servers or notion_token or drive_token or gmail_token or slack_token:
        try:
            agent = await _agent_brief(ctx, persona, servers or [], notion_token, drive_token, gmail_token, slack_token)
            if agent:
                return agent
        except Exception as exc:  # SDK/subprocess/tool failure — fall back to compose
            log.warning("prep agent path errored, falling back to compose: %s", exc)
    try:
        llm = await _llm_brief(ctx, persona)
        if llm:
            return llm
    except Exception as exc:  # LLM/network failure — fall back to deterministic
        log.warning("prep LLM compose errored, using offline brief: %s", exc)
    return _offline_brief(ctx)
