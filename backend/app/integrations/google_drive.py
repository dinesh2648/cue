"""Google Drive API — read the signed-in user's docs with their OAuth token.

Direct REST (no hosted MCP for Drive), so a connected Drive is actually queryable by the
agent: full-text search for relevant files, then export/read their text. Scope: drive.readonly.
"""
from __future__ import annotations

import logging

import httpx

log = logging.getLogger("copilot.gdrive")

_FILES_URL = "https://www.googleapis.com/drive/v3/files"
_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def search(token: str, query: str, k: int = 6) -> list[dict]:
    """Full-text search the user's Drive. Returns [{id, name, mimeType, modifiedTime, url}]."""
    q = (query or "").replace("\\", " ").replace("'", " ").strip()
    drive_q = f"fullText contains '{q}' and trashed = false" if q else "trashed = false"
    params = {
        "q": drive_q,
        "pageSize": str(max(1, min(k, 20))),
        "fields": "files(id,name,mimeType,modifiedTime,webViewLink)",
        "orderBy": "modifiedTime desc",
        "corpora": "user",
        "supportsAllDrives": "true",
        "includeItemsFromAllDrives": "true",
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.get(_FILES_URL, headers=_headers(token), params=params)
        r.raise_for_status()
        files = r.json().get("files", []) or []
    return [
        {
            "id": f.get("id"),
            "name": f.get("name", ""),
            "mimeType": f.get("mimeType", ""),
            "modified": f.get("modifiedTime", ""),
            "url": f.get("webViewLink", ""),
        }
        for f in files
    ]


async def read_file(token: str, file_id: str, max_chars: int = 4000) -> str:
    """Return a file's text. Exports Google Docs/Sheets/Slides as text; downloads plain files."""
    if not file_id:
        return ""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        meta = await c.get(
            f"{_FILES_URL}/{file_id}",
            headers=_headers(token),
            params={"fields": "mimeType,name", "supportsAllDrives": "true"},
        )
        meta.raise_for_status()
        mime = meta.json().get("mimeType", "")
        if mime.startswith("application/vnd.google-apps"):
            # Native Google file → export to plain text (docs/slides) or CSV (sheets).
            export_mime = "text/csv" if "spreadsheet" in mime else "text/plain"
            r = await c.get(
                f"{_FILES_URL}/{file_id}/export",
                headers=_headers(token),
                params={"mimeType": export_mime},
            )
        else:
            r = await c.get(
                f"{_FILES_URL}/{file_id}",
                headers=_headers(token),
                params={"alt": "media", "supportsAllDrives": "true"},
            )
        r.raise_for_status()
        text = r.text or ""
    return text[:max_chars]
