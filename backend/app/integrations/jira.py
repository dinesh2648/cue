"""Jira Cloud API (write) — create issues with the user's OAuth token.

Best-effort: resolves the user's first accessible Jira site (cloudid) and first project,
then creates a Task. Raises if no site/project is reachable so the caller records a draft.
"""
from __future__ import annotations

import logging

import httpx

log = logging.getLogger("copilot.jira")
_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json", "Content-Type": "application/json"}


def _adf(text: str) -> dict:
    """Plain text → Atlassian Document Format (Jira description field)."""
    paras = [p for p in (text or "").split("\n") if p.strip()] or [""]
    return {
        "type": "doc", "version": 1,
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": p[:1900]}]} for p in paras],
    }


async def create_issue(token: str, summary: str, description: str = "", project_key: str | None = None) -> dict:
    """Create a Jira Task. Returns {key, url}. Raises on no accessible site/project."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        res = await c.get("https://api.atlassian.com/oauth/token/accessible-resources", headers=_headers(token))
        res.raise_for_status()
        sites = res.json()
        if not sites:
            raise RuntimeError("No accessible Jira site for this token.")
        cloud_id = sites[0]["id"]
        site_url = sites[0].get("url", "")
        base = f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3"

        if not project_key:
            pr = await c.get(f"{base}/project/search?maxResults=1", headers=_headers(token))
            pr.raise_for_status()
            vals = pr.json().get("values", [])
            if not vals:
                raise RuntimeError("No Jira project available to create the issue in.")
            project_key = vals[0]["key"]

        payload = {
            "fields": {
                "project": {"key": project_key},
                "summary": summary[:250],
                "description": _adf(description),
                "issuetype": {"name": "Task"},
            }
        }
        r = await c.post(f"{base}/issue", headers=_headers(token), json=payload)
        r.raise_for_status()
        data = r.json()
    key = data.get("key", "")
    return {"key": key, "url": f"{site_url}/browse/{key}" if site_url and key else ""}


async def list_projects(token: str) -> list[dict]:
    """Projects the token can file into: [{key, name}]. [] if no accessible site/projects."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        res = await c.get("https://api.atlassian.com/oauth/token/accessible-resources", headers=_headers(token))
        res.raise_for_status()
        sites = res.json()
        if not sites:
            return []
        base = f"https://api.atlassian.com/ex/jira/{sites[0]['id']}/rest/api/3"
        pr = await c.get(f"{base}/project/search?maxResults=50", headers=_headers(token))
        pr.raise_for_status()
        return [{"key": v.get("key", ""), "name": v.get("name", "")} for v in pr.json().get("values", [])]
