"""Notion API (read) — works with a PAT or an OAuth access token (both are Bearer).

Used instead of Notion's hosted MCP (mcp.notion.com/mcp), which requires its own OAuth
handshake and rejects a static PAT. The plain REST API works with either token type.
"""
from __future__ import annotations

import logging

import httpx

log = logging.getLogger("copilot.notion")

_API = "https://api.notion.com/v1"
_VERSION = "2022-06-28"
_TIMEOUT = httpx.Timeout(12.0, connect=5.0)


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Notion-Version": _VERSION, "Content-Type": "application/json"}


def _title_of(obj: dict) -> str:
    if obj.get("object") == "database":
        return "".join(p.get("plain_text", "") for p in obj.get("title", []))
    for v in (obj.get("properties", {}) or {}).values():
        if v.get("type") == "title" and v.get("title"):
            return "".join(p.get("plain_text", "") for p in v["title"])
    return obj.get("id", "")


async def search(token: str, query: str = "", k: int = 6) -> list[dict]:
    """Search pages/databases the integration can see. Raises on API error."""
    body: dict = {"page_size": k}
    if query:
        body["query"] = query
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.post(f"{_API}/search", headers=_headers(token), json=body)
        r.raise_for_status()
        data = r.json()
    return [
        {"id": x.get("id"), "object": x.get("object"), "title": _title_of(x), "url": x.get("url", "")}
        for x in data.get("results", [])
    ]


def _md_to_blocks(md: str) -> list[dict]:
    """Minimal Markdown → Notion blocks (headings, bullets, paragraphs). Capped at 95."""
    blocks: list[dict] = []
    for raw in md.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        def _rt(text: str) -> list[dict]:
            return [{"type": "text", "text": {"content": text[:1900]}}]
        if line.startswith("### "):
            blocks.append({"type": "heading_3", "heading_3": {"rich_text": _rt(line[4:])}})
        elif line.startswith("## "):
            blocks.append({"type": "heading_2", "heading_2": {"rich_text": _rt(line[3:])}})
        elif line.startswith("# "):
            blocks.append({"type": "heading_1", "heading_1": {"rich_text": _rt(line[2:])}})
        elif line.lstrip().startswith(("- ", "* ")):
            blocks.append({"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": _rt(line.lstrip()[2:])}})
        else:
            blocks.append({"type": "paragraph", "paragraph": {"rich_text": _rt(line)}})
        if len(blocks) >= 95:
            break
    return blocks or [{"type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": md[:1900]}}]}}]


async def create_page(token: str, title: str, markdown_body: str) -> dict:
    """Create a Notion page under the first page the integration can access.

    Returns {id, url}. Raises if no parent is accessible or the token lacks write capability.
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        # Find a parent page the integration can write under.
        s = await c.post(f"{_API}/search", headers=_headers(token),
                         json={"page_size": 5, "filter": {"value": "page", "property": "object"}})
        s.raise_for_status()
        pages = [r for r in s.json().get("results", []) if r.get("object") == "page"]
        if not pages:
            raise RuntimeError("No Notion page is shared with the integration to create under.")
        parent_id = pages[0]["id"]
        r = await c.post(
            f"{_API}/pages",
            headers=_headers(token),
            json={
                "parent": {"page_id": parent_id},
                "properties": {"title": {"title": [{"text": {"content": title[:200]}}]}},
                "children": _md_to_blocks(markdown_body),
            },
        )
        r.raise_for_status()
        data = r.json()
    return {"id": data.get("id"), "url": data.get("url", "")}


async def archive_page(token: str, page_id: str) -> None:
    """Undo a Notion write — archive (soft-delete) a page by id."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.patch(f"{_API}/pages/{page_id}", headers=_headers(token), json={"archived": True})
        if r.status_code not in (200, 404):
            r.raise_for_status()


async def page_text(token: str, page_id: str, max_blocks: int = 50) -> str:
    """Concatenated plain text of a page's top-level blocks."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.get(
            f"{_API}/blocks/{page_id}/children",
            headers=_headers(token),
            params={"page_size": max_blocks},
        )
        r.raise_for_status()
        data = r.json()
    lines = []
    for b in data.get("results", []):
        bt = b.get("type")
        block = b.get(bt) if isinstance(b.get(bt), dict) else {}
        rich = block.get("rich_text", []) if isinstance(block, dict) else []
        txt = "".join(rt.get("plain_text", "") for rt in rich)
        if txt:
            lines.append(txt)
    return "\n".join(lines)[:4000]
