"""Gmail API — read the signed-in user's mail with their OAuth token.

Direct REST (no hosted MCP for Gmail), so a connected Gmail is actually queryable by the
agent: search threads (e.g. with a customer/domain), then read a message's text. Scope:
gmail.readonly.
"""
from __future__ import annotations

import base64
import logging

import httpx

log = logging.getLogger("copilot.gmail")

_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _hdr(headers: list[dict], name: str) -> str:
    for h in headers or []:
        if (h.get("name") or "").lower() == name.lower():
            return h.get("value", "")
    return ""


async def search(token: str, query: str, k: int = 8) -> list[dict]:
    """Search the user's mail (Gmail query syntax). Returns [{id, from, subject, date, snippet}]."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        lst = await c.get(
            f"{_BASE}/messages",
            headers=_headers(token),
            params={"q": query or "", "maxResults": str(max(1, min(k, 20)))},
        )
        lst.raise_for_status()
        ids = [m.get("id") for m in (lst.json().get("messages") or []) if m.get("id")]
        out: list[dict] = []
        for mid in ids:
            m = await c.get(
                f"{_BASE}/messages/{mid}",
                headers=_headers(token),
                params={"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]},
            )
            if m.status_code != 200:
                continue
            d = m.json()
            hs = (d.get("payload") or {}).get("headers", [])
            out.append({
                "id": mid,
                "from": _hdr(hs, "From"),
                "subject": _hdr(hs, "Subject"),
                "date": _hdr(hs, "Date"),
                "snippet": d.get("snippet", ""),
            })
    return out


def _decode_part(part: dict) -> str:
    data = (part.get("body") or {}).get("data")
    if not data:
        return ""
    try:
        return base64.urlsafe_b64decode(data + "===").decode("utf-8", "replace")
    except Exception:  # pragma: no cover
        return ""


def _extract_text(payload: dict) -> str:
    """Prefer text/plain; walk multipart parts recursively."""
    mime = payload.get("mimeType", "")
    if mime == "text/plain":
        return _decode_part(payload)
    parts = payload.get("parts") or []
    for p in parts:
        if p.get("mimeType") == "text/plain":
            t = _decode_part(p)
            if t:
                return t
    # fall back to any nested text we can find
    for p in parts:
        t = _extract_text(p)
        if t:
            return t
    return ""


async def read_message(token: str, msg_id: str, max_chars: int = 4000) -> str:
    """Return a message's plain-text body (with a short header line)."""
    if not msg_id:
        return ""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.get(f"{_BASE}/messages/{msg_id}", headers=_headers(token), params={"format": "full"})
        r.raise_for_status()
        d = r.json()
    payload = d.get("payload") or {}
    hs = payload.get("headers", [])
    head = f"From: {_hdr(hs, 'From')}\nSubject: {_hdr(hs, 'Subject')}\nDate: {_hdr(hs, 'Date')}\n\n"
    body = _extract_text(payload) or d.get("snippet", "")
    return (head + body)[:max_chars]
