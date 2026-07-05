"""Read a user's IN-PROCESS sources (Gmail, Drive, Slack) for a query.

These three have no usable hosted MCP, so the live-federated agent (messages_mcp) and the
remote-MCP prep brief can't reach them on their own. We pre-fetch the relevant matches here —
searching each source, and reading the actual email bodies / file text / channel thread for the
top hits — so their REAL content (not just titles) lands everywhere the copilot reasons:
prep notes, live in-meeting answers, and the post-meeting summary alike.

Single source of truth: prep_ops, the packs' deep_answer, and summary all call gather_comms().
"""
from __future__ import annotations

import logging
import re

from sqlalchemy.orm import Session

from ..integrations import gmail as gmail_api
from ..integrations import google_calendar as calendar_api
from ..integrations import google_drive as drive_api
from ..integrations import notion as notion_api
from ..integrations import slack as slack_api
from .manager import get_access_token, get_connection, inprocess_read_tokens

log = logging.getLogger("copilot.live_sources")


async def _safe(coro):
    try:
        return await coro
    except Exception as exc:  # pragma: no cover - best-effort per source
        log.info("live_sources: source read failed (skipped): %s", exc)
        return []


async def _provider_token(db: Session, user_id: str, provider: str) -> str | None:
    """A live (non-demo) token for a connector read in-process (Notion PAT, Calendar)."""
    t = await get_access_token(db, user_id, provider)
    return None if (not t or t.startswith("demo-")) else t


_CAL_WORDS = {"meeting", "meetings", "calendar", "schedule", "scheduled", "upcoming", "agenda", "when", "invite", "call"}


# Slack search is KEYWORD-based (unlike Gmail/Drive full-text): a whole natural-language question
# matches nothing. Reduce it to salient terms before searching Slack.
_STOP = {
    "what", "whats", "what's", "how", "why", "when", "where", "who", "which", "the", "a", "an",
    "is", "are", "was", "were", "do", "does", "did", "of", "to", "in", "on", "at", "for", "about",
    "with", "and", "or", "our", "my", "me", "i", "we", "us", "you", "your", "any", "there", "that",
    "this", "these", "those", "can", "could", "would", "should", "tell", "give", "show", "get",
    "please", "status", "update", "latest", "recent", "happening", "going", "been", "have", "has",
}


def _keywords(q: str) -> str:
    toks = [re.sub(r"[^\w-]", "", w) for w in (q or "").lower().split()]
    kw = [w for w in toks if w and w not in _STOP and len(w) > 2]
    return " ".join(kw[:8]) or (q or "").strip()


async def gather_comms(
    db: Session,
    user_id: str | None,
    query: str,
    *,
    tokens: dict | None = None,
    read_bodies: bool = True,
    gmail_k: int = 6,
    drive_k: int = 4,
    slack_k: int = 5,
    notion: bool = True,
    calendar: bool = True,
) -> list[dict]:
    """Relevant items from the user's IN-PROCESS sources for `query`, as a list of {source, ...}
    dicts. Covers Gmail, Drive, Slack, Notion (PAT) and Calendar — every source that has no hosted
    MCP the agent could call itself. (Remote-MCP sources — Jira/GitHub/HubSpot/Notion-DCR — reach
    the agent directly as tools and aren't duplicated here.)

    read_bodies=True also reads the email body / file text / Notion page / top channel's recent
    thread for the best matches — richer, for prep & the summary (background, latency-tolerant).
    read_bodies=False stays at search snippets — lighter, for live in-meeting answers.

    `tokens` may be a pre-fetched {gmail, google_drive, slack} map (avoids a second token refresh
    when the caller already has them); Notion/Calendar tokens are resolved here as needed.
    """
    q = (query or "").strip()[:200]
    if not q or not user_id:
        return []
    if tokens is None:
        tokens = await inprocess_read_tokens(db, user_id)
    gmail_token = tokens.get("gmail")
    drive_token = tokens.get("google_drive")
    slack_token = tokens.get("slack")

    comms: list[dict] = []
    if gmail_token:
        hits = await _safe(gmail_api.search(gmail_token, q, k=gmail_k))
        for i, m in enumerate(hits):
            item = {"source": "gmail", **m}
            if read_bodies and i < 3 and m.get("id"):  # read the actual email body, not just the snippet
                body = await _safe(gmail_api.read_message(gmail_token, m["id"], max_chars=1200))
                if isinstance(body, str) and body.strip():
                    item["body"] = body
            comms.append(item)
    if drive_token:
        files = await _safe(drive_api.search(drive_token, q, k=drive_k))
        for i, d in enumerate(files):
            item = {"source": "drive", **d}
            if read_bodies and i < 2 and d.get("id"):  # read the file's text (Docs/Sheets/Slides), not just its name
                body = await _safe(drive_api.read_file(drive_token, d["id"], max_chars=1000))
                if isinstance(body, str) and body.strip():
                    item["body"] = body
            comms.append(item)
    slack_hits = 0
    if slack_token:
        # Slack search is keyword-based → reduce the question to salient terms, then fall back to the
        # raw query only if that yields nothing (short/proper-noun queries survive _keywords anyway).
        sq = _keywords(q)
        hits = await _safe(slack_api.search(slack_token, sq, k=slack_k))
        if not hits and sq != q:
            hits = await _safe(slack_api.search(slack_token, q, k=slack_k))
        slack_hits = len(hits)
        comms += [{"source": "slack", **sm} for sm in hits]
        if read_bodies:  # deepen: pull the top matched channel's recent thread, not just isolated hits
            top_ch = next((h.get("channel_id") for h in hits if h.get("channel_id")), None)
            if top_ch:
                hist = await _safe(slack_api.channel_history(slack_token, top_ch, limit=12))
                texts = [m.get("text", "") for m in hist if m.get("text")][:12]
                if texts:
                    ch_name = next((h.get("channel") for h in hits if h.get("channel_id") == top_ch), "")
                    comms.append({"source": "slack", "channel": ch_name, "recent_messages": texts})

    notion_hits = 0
    if notion:
        # PAT connections are read in-process here; a DCR (OAuth) Notion flows via the remote MCP
        # server instead — its token isn't a Notion API key, so skip it to avoid a guaranteed 401.
        nconn = get_connection(db, user_id, "notion")
        notion_is_dcr = bool(nconn and (nconn.oauth_meta or {}).get("token_endpoint"))
        notion_token = None if (not nconn or notion_is_dcr) else await _provider_token(db, user_id, "notion")
        if notion_token:
            pages = await _safe(notion_api.search(notion_token, q, k=4))
            notion_hits = len(pages)
            for i, p in enumerate(pages):
                item = {"source": "notion", "title": p.get("title", ""), "url": p.get("url", ""), "id": p.get("id")}
                if read_bodies and i < 2 and p.get("id"):
                    body = await _safe(notion_api.page_text(notion_token, p["id"]))
                    if isinstance(body, str) and body.strip():
                        item["body"] = body
                comms.append(item)

    cal_count = 0
    if calendar:
        cal_token = await _provider_token(db, user_id, "google_calendar")
        if cal_token:
            events = await _safe(calendar_api.list_upcoming(cal_token, max_results=10, days=30))
            kws = {w for w in _keywords(q).split() if len(w) > 2}
            cal_ish = bool(kws & _CAL_WORDS) or any(w in q.lower() for w in ("next meeting", "my calendar"))
            for ev in events:
                hay = (ev.get("title", "") + " " + " ".join(ev.get("attendees") or [])).lower()
                if cal_ish or (kws and any(k in hay for k in kws)):
                    comms.append({
                        "source": "calendar", "title": ev.get("title", ""), "start": ev.get("start", ""),
                        "attendees": ev.get("attendees") or [], "url": ev.get("html_link", ""),
                    })
                    cal_count += 1
                if cal_count >= 5:
                    break

    log.info(
        "gather_comms: q=%r tokens(gmail=%s drive=%s slack=%s) items=%d slack_hits=%d notion_hits=%d cal=%d",
        q[:80], bool(gmail_token), bool(drive_token), bool(slack_token),
        len(comms), slack_hits, notion_hits, cal_count,
    )
    return comms


async def available_inprocess(db: Session, user_id: str | None) -> list[str]:
    """Display names of the in-process sources gather_comms will search for this user (Gmail, Drive,
    Slack, Notion-PAT, Calendar) — so the UI can report them as 'searched' alongside the remote-MCP
    servers, which is the only place they'd otherwise appear."""
    if not user_id:
        return []
    tk = await inprocess_read_tokens(db, user_id)
    out: list[str] = []
    if tk.get("gmail"):
        out.append("Gmail")
    if tk.get("google_drive"):
        out.append("Google Drive")
    if tk.get("slack"):
        out.append("Slack")
    nconn = get_connection(db, user_id, "notion")
    if nconn and not (nconn.oauth_meta or {}).get("token_endpoint") and await _provider_token(db, user_id, "notion"):
        out.append("Notion")  # PAT connection (DCR Notion is already a remote MCP server)
    if await _provider_token(db, user_id, "google_calendar"):
        out.append("Google Calendar")
    return out


_LABEL = {"gmail": "Email", "drive": "Drive", "slack": "Slack", "notion": "Notion", "calendar": "Calendar"}


def format_comms(comms: list[dict], *, max_chars: int = 6000) -> str:
    """Compact text rendering of gather_comms output for prompt injection (live answers, summary)."""
    if not comms:
        return ""
    lines: list[str] = []
    for c in comms:
        src = _LABEL.get(c.get("source", ""), (c.get("source") or "").title())
        if c.get("recent_messages"):
            ch = c.get("channel") or "channel"
            lines.append(f"- [{src}] recent thread in #{ch}:")
            for t in c["recent_messages"]:
                if t.strip():
                    lines.append(f"    • {t.strip()[:200]}")
            continue
        if c.get("source") == "calendar":
            att = ", ".join(c.get("attendees") or [])[:80]
            head = f"- [{src}] {c.get('title', '')[:120]} — {c.get('start', '')}"
            lines.append(head + (f" (with {att})" if att else ""))
            continue
        title = (c.get("subject") or c.get("title") or c.get("name") or c.get("text") or c.get("channel") or "").strip()
        meta = (c.get("from") or c.get("user") or c.get("channel") or "")
        head = f"- [{src}] {title[:160]}"
        if meta:
            head += f" — {str(meta)[:60]}"
        lines.append(head)
        body = (c.get("body") or c.get("snippet") or "").strip()
        if body:
            lines.append(f"    {body[:600]}")
    return "\n".join(lines)[:max_chars]


_SOURCE_META = {
    "gmail": ("Gmail", "email"),
    "drive": ("Google Drive", "document"),
    "slack": ("Slack", "connector"),
    "notion": ("Notion", "document"),
    "calendar": ("Google Calendar", "connector"),
}


def comms_sources(comms: list[dict]) -> list[dict]:
    """Source chips for whichever in-process sources actually returned content — the live-answer
    parser only credits MCP tool calls, so without this Gmail/Drive/Slack we hand the model are
    invisible in the answer's sources even when they were consulted."""
    seen: list[str] = []
    out: list[dict] = []
    for c in comms or []:
        s = c.get("source")
        if s and s not in seen:
            seen.append(s)
            label, stype = _SOURCE_META.get(s, ((s or "").title(), "connector"))
            out.append({
                "label": label, "type": stype, "detail": "live",
                "url": c.get("permalink") or c.get("webViewLink") or c.get("url") or "",
            })
    return out


def comms_evidence(comms: list[dict], k: int = 3) -> list[str]:
    """A few short evidence snippets drawn from the in-process content, for the answer card."""
    ev: list[str] = []
    for c in comms or []:
        if c.get("recent_messages"):
            ev.append(f"Slack #{c.get('channel', '')}: " + " / ".join(c["recent_messages"][:2])[:180])
        elif c.get("source") == "calendar":
            ev.append(f"Calendar: {c.get('title', '')} — {c.get('start', '')}"[:180])
        else:
            head = (c.get("subject") or c.get("title") or c.get("name") or c.get("text") or "").strip()
            body = (c.get("body") or c.get("snippet") or "").strip()
            snip = (f"{head} — {body}" if head and body else head or body)[:180]
            if snip:
                ev.append(snip)
        if len(ev) >= k:
            break
    return ev
