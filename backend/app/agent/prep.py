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

_SECTIONS_SALES = (
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
_SECTIONS_TECH = (
    "Write GitHub-flavored markdown with EXACTLY these sections, in order, omitting a section "
    "only if you truly have nothing for it:\n"
    "## TL;DR  — 2-3 bullets: who, why this meeting, the one thing to get right.\n"
    "## Where we left off  — open threads, decisions or follow-ups from prior meetings, messages, PRs and tickets.\n"
    "## Relevant work  — related Jira issues, open pull requests, design docs and recent changes to reference.\n"
    "## Who's in the room  — each attendee: name, likely role, any prior interaction.\n"
    "## Talking points  — 3-5 specific technical topics or decisions to raise, tied to the work.\n"
    "## Risks & blockers  — open questions, dependencies, technical risks, anything to unblock.\n"
    "Be concrete and concise. Bullets over paragraphs. No preamble, no sign-off."
)


def _sections(persona: str) -> str:
    return _SECTIONS_TECH if persona == "tech" else _SECTIONS_SALES

# Tool-using prompt (agent path): research LIVE across connected sources + web. Persona picks
# both the framing and the section scaffold — a Tech brief is engineering-shaped, not sales.
def _system_agent(persona: str) -> str:
    if persona == "tech":
        intro = (
            "You are a meeting-prep researcher for a software engineer. You produce a tight, "
            "skimmable brief to read in 60 seconds before an engineering / technical meeting.\n"
            "Use the tools to research LIVE across the connected sources: Jira (open issues, "
            "sprints), GitHub (PRs, issues, recent changes), docs (Drive/Notion) and messages "
            "(Slack/Gmail). Ground every claim in what you find; never invent specifics.\n"
        )
    else:
        intro = (
            "You are a meeting-prep researcher for a sales engineer / AE. You produce a tight, "
            "skimmable preparation brief the rep can read in 60 seconds before a customer call.\n"
            "Use the tools to research the customer LIVE: their CRM record (HubSpot — deals, "
            "tickets, owner, lifecycle), recent email threads (Gmail), relevant docs (Drive/Notion), "
            "and the public web (company news, the attendees' roles). Ground every claim in what "
            "you find; never invent specifics.\n"
        )
    return intro + _sections(persona)


# Compose-only prompt (no tools): synthesize STRICTLY from the context block provided.
def _system_compose(persona: str) -> str:
    if persona == "tech":
        intro = (
            "You are a meeting-prep assistant for a software engineer. Using ONLY the context "
            "provided below (prior meeting notes, related tickets/PRs, internal docs, attendee "
            "list), write a tight, skimmable brief to read in 60 seconds.\n"
            "You have NO tools — do not call any, do not output function calls, and do not invent "
            "specifics not present in the context. If the context is thin, keep the brief short and "
            "note what to confirm live.\n"
        )
    else:
        intro = (
            "You are a meeting-prep assistant for a sales engineer / AE. Using ONLY the context "
            "provided below (prior meeting notes, CRM snapshot, internal docs, attendee list), "
            "write a tight, skimmable preparation brief the rep can read in 60 seconds.\n"
            "You have NO tools — do not call any, do not output function calls, and do not invent "
            "specifics not present in the context. If the context is thin, keep the brief short and "
            "note what to confirm live.\n"
        )
    return intro + _sections(persona)

_TECH_EXTRA = (
    " This is an engineering/technical meeting — favor Jira/GitHub/Drive context (open issues, "
    "PRs, design docs) and DO NOT use LinkedIn."
    " For Jira: FIRST call getAccessibleAtlassianResources to get the cloudId, pass it to every "
    "Jira tool, and use a BOUNDED JQL (add a restriction like project, assignee = currentUser(), "
    "statusCategory != Done, or created >= -30d — unbounded queries are rejected)."
)


def _context_block(ctx: dict, persona: str = "sales") -> str:
    """Render the internal context we gathered into a compact prompt block (persona-framed)."""
    is_tech = persona == "tech"
    parts: list[str] = []
    preamble = (ctx.get("profile_context") or "").strip()
    if preamble:  # always-on advisory context: who this brief is for + company + role
        parts.append(preamble)
    parts += [
        f"Event: {ctx.get('title', '')}",
        f"When: {ctx.get('start', '')}",
    ]
    if not is_tech:  # "Customer" is a sales framing; a tech sync often has no external customer
        parts.append(f"Customer: {ctx.get('customer') or 'unknown'}")
    parts.append(f"Attendees: {', '.join(ctx.get('external_attendees') or []) or 'none listed'}")
    parts.append(f"Organizer: {ctx.get('organizer', '')}")
    crm = ctx.get("crm") or {}
    if not is_tech and crm.get("company"):  # CRM is sales-only context
        parts.append("CRM (HubSpot) snapshot:\n" + json.dumps(crm)[:1500])
    history = ctx.get("history") or []
    if history:
        label = "Prior related meetings" if is_tech else "Prior meetings with this customer"
        parts.append(f"{label}:\n" + json.dumps(history)[:2000])
    docs = ctx.get("docs") or []
    if docs:
        parts.append("Relevant internal docs:\n" + json.dumps(docs)[:1000])
    comms = ctx.get("comms") or []
    if comms:
        parts.append(
            "Recent emails and Drive files (with content), plus matching Slack messages and the "
            "top channel's recent thread, from your connected accounts — use what's relevant to "
            "the attendees and topic, ignore the rest:\n"
            + json.dumps(comms)[:7500]
        )
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
        if not (name and url) or s.get("inprocess"):  # in-process sources (PAT-Notion) handled separately
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

    system = _system_agent(persona)
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
        "Prepare me for this upcoming meeting. Research across my connected tools"
        + (" and the web" if persona != "tech" else "")
        + ", then write the brief.\n\n" + _context_block(ctx, persona)
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


_COMM_LABEL = {"gmail": "Gmail", "drive": "Google Drive", "slack": "Slack"}


def _comm_sources(ctx: dict) -> list[dict]:
    """Attribute the pre-fetched in-process comms (Gmail/Drive/Slack) present in the context."""
    seen = {c.get("source") for c in (ctx.get("comms") or []) if c.get("source")}
    return [
        {"label": f"{_COMM_LABEL.get(s, s.title())} (your account)", "type": "connector", "detail": "your access", "url": ""}
        for s in sorted(seen)
    ]


_MCP_BETA = "mcp-client-2025-04-04"


async def _mcp_brief(ctx: dict, persona: str, servers: list[dict], user_id: str | None = None) -> dict | None:
    """Research the brief LIVE via Anthropic's native MCP connector over the user's remote MCP
    servers (GitHub, Jira, HubSpot, Notion-DCR). This is the path that WORKS in Docker, where the
    Claude Agent SDK (used by _agent_brief) isn't installed. Returns None to fall back to compose.

    Note: in-process sources (Gmail/Drive/Slack, Notion-PAT) are not reachable here — they need the
    agent-SDK tool loop — so this researches whatever the user has as a hosted MCP server.
    """
    from ..config import settings

    remote = [s for s in servers if s.get("url") and s.get("token") and not s.get("inprocess")]
    if not settings.anthropic_api_key or not remote:
        return None
    try:
        from anthropic import AsyncAnthropic
    except ImportError:  # pragma: no cover
        return None

    system = _system_agent(persona) + (_TECH_EXTRA if persona == "tech" else "")
    connected = ", ".join(sorted({s.get("name", "") for s in remote if s.get("name")}))
    user_msg = (
        "Prepare me for this upcoming meeting. Research LIVE across my connected tools "
        f"({connected}) — pull the open issues, PRs, tickets and recent activity that are actually "
        "relevant to this meeting and the attendees — then write the brief. Ground every claim in "
        "what the tools return; if a tool returns nothing relevant, say so rather than speculating.\n\n"
        + _context_block(ctx, persona)
    )
    payload = [{"type": "url", "url": s["url"], "name": s["name"], "authorization_token": s["token"]} for s in remote]
    # Hard timeout so a slow/hung remote MCP server can't make prep hang for minutes (which left the
    # brief stuck "generating…" and the client polling endlessly). On timeout we return None and fall
    # back to the fast compose brief — prep always finishes in bounded time.
    from ..integrations.llm import cached_system
    client = AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=75.0)
    try:
        resp = await client.beta.messages.create(
            # 2500 comfortably fits a tight 6-section skimmable brief (~1800 words) without ever
            # truncating a section, while capping the occasional runaway (was 4000).
            # cached_system caches the stable system (+ MCP tool block) across the agentic loop.
            model=settings.anthropic_model, max_tokens=2500, system=cached_system(system),
            messages=[{"role": "user", "content": user_msg}],
            mcp_servers=payload, betas=[_MCP_BETA],
        )
    except Exception as exc:
        log.warning("prep mcp research failed (or timed out); falling back to compose: %s", exc)
        return None

    try:  # cost telemetry (best-effort)
        from ..observability.usage import record_usage
        tool_calls = sum(1 for b in getattr(resp, "content", []) if getattr(b, "type", "") == "mcp_tool_use")
        record_usage(call_type="prep_research", model=settings.anthropic_model,
                     usage=getattr(resp, "usage", None), user_id=user_id, tool_calls=tool_calls)
    except Exception:  # pragma: no cover
        pass

    parts, used = [], set()
    for block in resp.content:
        bt = getattr(block, "type", "")
        if bt == "text":
            parts.append(block.text)
        elif bt == "mcp_tool_use":
            parts.clear()  # drop pre-tool narration; keep only the final written brief
            nm = getattr(block, "server_name", "") or getattr(block, "name", "")
            if nm:
                used.add(nm.split("__")[0] if "__" in nm else nm)
    markdown = "\n".join(p.rstrip() for p in parts if p.strip()).strip()
    if "## " in markdown:
        markdown = markdown[markdown.index("## "):]
    if not markdown:
        return None
    sources = [{"label": f"{u.replace('_', ' ').title()} (your account)", "type": "connector", "detail": "live · your access", "url": ""} for u in sorted(used)]
    sources += _comm_sources(ctx)
    return {"markdown": markdown, "sources": sources or [{"label": "Connected tools (live)", "type": "connector", "detail": "live", "url": ""}], "engine": "claude+mcp"}


async def _llm_brief(ctx: dict, persona: str) -> dict | None:
    """No agent/connected tools — compose a brief STRICTLY from the internal context we have."""
    system = _system_compose(persona)  # no _TECH_EXTRA here — it's Jira tool mechanics, useless without tools
    out = await llm_complete(system, _context_block(ctx, persona), max_tokens=1200, temperature=0.3, timeout=60, call_type="prep_compose")
    if not out:
        return None
    label = "Prior meetings & internal context" if persona == "tech" else "Prior meetings & CRM"
    return {"markdown": out.strip(), "sources": [{"label": label, "type": "document", "detail": "internal", "url": ""}, *_comm_sources(ctx)], "engine": "llm"}


def _offline_brief(ctx: dict, persona: str = "sales") -> dict:
    """Last resort — a deterministic brief from internal context (no LLM available)."""
    is_tech = persona == "tech"
    lines = [f"## {ctx.get('title') or 'Upcoming meeting'}", ""]
    if not is_tech and ctx.get("customer"):
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
    if not is_tech and crm:  # CRM/account snapshot is a sales section
        lines += ["", "## Account snapshot", f"- {json.dumps(crm)[:300]}"]
    if len(lines) <= 2:
        connect = "Jira, GitHub, Notion, Drive or Slack" if is_tech else "HubSpot, Notion, Drive or Gmail"
        lines.append(f"_No prior context found. Connect {connect} for a researched brief._")
    return {"markdown": "\n".join(lines), "sources": [], "engine": "offline"}


async def generate_prep(
    ctx: dict, *, persona: str, servers: list[dict] | None,
    notion_token: str | None = None, drive_token: str | None = None, gmail_token: str | None = None,
    slack_token: str | None = None, user_id: str | None = None,
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
    # Live research via Anthropic's MCP connector — the path that works in Docker (no agent-SDK).
    if servers:
        try:
            mcp = await _mcp_brief(ctx, persona, servers, user_id=user_id)
            if mcp:
                return mcp
        except Exception as exc:
            log.warning("prep mcp path errored, falling back to compose: %s", exc)
    try:
        llm = await _llm_brief(ctx, persona)
        if llm:
            return llm
    except Exception as exc:  # LLM/network failure — fall back to deterministic
        log.warning("prep LLM compose errored, using offline brief: %s", exc)
    return _offline_brief(ctx, persona)


async def generate_prep_quick(ctx: dict, persona: str) -> dict:
    """Phase 1 — a FAST brief from the context we already gathered (no live tool research).

    Compose from CRM/history/emails/docs already in `ctx`; deterministic offline brief if the LLM
    is unavailable. Always returns something usable in seconds, so the user never stares at a spinner
    while the slow live research runs.
    """
    try:
        llm = await _llm_brief(ctx, persona)
        if llm:
            return llm
    except Exception as exc:  # pragma: no cover
        log.warning("prep quick compose errored, using offline brief: %s", exc)
    return _offline_brief(ctx, persona)


async def generate_prep_deep(
    ctx: dict, *, persona: str, servers: list[dict] | None,
    notion_token: str | None = None, drive_token: str | None = None, gmail_token: str | None = None,
    slack_token: str | None = None, user_id: str | None = None,
) -> dict | None:
    """Phase 2 — the RICHER brief that researches the user's live connected tools + web.

    Returns None when there's nothing to research or the research produced nothing — the caller then
    keeps the fast phase-1 brief rather than downgrading it.
    """
    if servers or notion_token or drive_token or gmail_token or slack_token:
        try:
            agent = await _agent_brief(ctx, persona, servers or [], notion_token, drive_token, gmail_token, slack_token)
            if agent:
                return agent
        except Exception as exc:  # SDK/subprocess/tool failure — try the MCP-connector path
            log.warning("prep deep agent path errored: %s", exc)
    if servers:
        try:
            mcp = await _mcp_brief(ctx, persona, servers, user_id=user_id)
            if mcp:
                return mcp
        except Exception as exc:
            log.warning("prep deep mcp path errored: %s", exc)
    return None
