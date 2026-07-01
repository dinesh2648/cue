"""Slack Web API — read the user's channels, threads and search with their token.

Direct REST (no hosted MCP), so a connected Slack is queryable by the agent: search
messages, read a channel's recent history, read a thread. Works with a User OAuth token
(xoxp-, best — searches as the user) or a bot token (xoxb-, limited to channels the bot is in;
search is unavailable for bot tokens).
"""
from __future__ import annotations

import logging

import httpx

log = logging.getLogger("copilot.slack")

_BASE = "https://slack.com/api"
_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _get(token: str, method: str, params: dict) -> dict:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.get(f"{_BASE}/{method}", headers=_headers(token), params=params)
        r.raise_for_status()
        data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"slack {method} error: {data.get('error', 'unknown')}")
    return data


async def search(token: str, query: str, k: int = 8) -> list[dict]:
    """Search messages (needs a user token with search:read). Returns [{text, user, channel, ts, permalink}]."""
    data = await _get(token, "search.messages", {"query": query or "", "count": max(1, min(k, 20))})
    matches = ((data.get("messages") or {}).get("matches")) or []
    return [
        {
            "text": m.get("text", ""),
            "user": (m.get("username") or m.get("user") or ""),
            "channel": (m.get("channel") or {}).get("name", ""),
            "ts": m.get("ts", ""),
            "permalink": m.get("permalink", ""),
        }
        for m in matches[:k]
    ]


async def channel_history(token: str, channel_id: str, limit: int = 20) -> list[dict]:
    """Recent messages in a channel (needs channels:history). channel_id is the Slack id (Cxxxx)."""
    data = await _get(token, "conversations.history", {"channel": channel_id, "limit": max(1, min(limit, 50))})
    msgs = data.get("messages") or []
    return [{"text": m.get("text", ""), "user": m.get("user", ""), "ts": m.get("ts", "")} for m in msgs]


async def find_channel(token: str, name: str) -> str | None:
    """Resolve a channel name (e.g. 'engineering') to its id, for channel_history."""
    name = (name or "").lstrip("#").lower()
    if not name:
        return None
    data = await _get(token, "conversations.list", {"limit": 200, "types": "public_channel,private_channel"})
    for ch in data.get("channels", []) or []:
        if (ch.get("name") or "").lower() == name:
            return ch.get("id")
    return None
