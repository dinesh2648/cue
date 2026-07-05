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

from sqlalchemy.orm import Session

from ..integrations import gmail as gmail_api
from ..integrations import google_drive as drive_api
from ..integrations import slack as slack_api
from .manager import inprocess_read_tokens

log = logging.getLogger("copilot.live_sources")


async def _safe(coro):
    try:
        return await coro
    except Exception:  # pragma: no cover - best-effort per source
        return []


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
) -> list[dict]:
    """Relevant Gmail / Drive / Slack items for `query`, as a list of {source, ...} dicts.

    read_bodies=True also reads the email body / file text / top channel's recent thread for the
    best matches — richer, for prep & the summary (background, latency-tolerant). read_bodies=False
    stays at search snippets — lighter, for live in-meeting answers (latency-sensitive).

    `tokens` may be a pre-fetched {gmail, google_drive, slack} map (avoids a second token refresh
    when the caller already has them); otherwise they're resolved here.
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
    if slack_token:
        hits = await _safe(slack_api.search(slack_token, q, k=slack_k))
        comms += [{"source": "slack", **sm} for sm in hits]
        if read_bodies:  # deepen: pull the top matched channel's recent thread, not just isolated hits
            top_ch = next((h.get("channel_id") for h in hits if h.get("channel_id")), None)
            if top_ch:
                hist = await _safe(slack_api.channel_history(slack_token, top_ch, limit=12))
                texts = [m.get("text", "") for m in hist if m.get("text")][:12]
                if texts:
                    ch_name = next((h.get("channel") for h in hits if h.get("channel_id") == top_ch), "")
                    comms.append({"source": "slack", "channel": ch_name, "recent_messages": texts})
    return comms


_LABEL = {"gmail": "Email", "drive": "Drive", "slack": "Slack"}


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
