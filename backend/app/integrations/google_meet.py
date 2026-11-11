"""Google Meet REST API — post-meeting transcripts (recap WITHOUT a Recall bot).

After a Meet call ends, Workspace exposes the official transcript via the Meet REST API:
  conferenceRecords (one per meeting instance)
    -> transcripts (one per transcription session; ready at state FILE_GENERATED)
      -> entries (participant + text + timing — ordered by start time)

We reuse the user's Google Calendar OAuth token (same `google` credential) plus the added
`meetings.space.readonly` scope. Two hard requirements outside our control:
  1. a Workspace edition that includes Meet transcripts (not consumer gmail), and
  2. transcription actually turned ON for the call — otherwise there is nothing to fetch.

Everything here is best-effort and never raises to the caller: on any API failure it returns
None (treated as "not ready yet, retry later") so the ingest loop can't be taken down.
"""
from __future__ import annotations

import logging
import re

import httpx

from ..config import settings

log = logging.getLogger("copilot.google_meet")

_BASE = "https://meet.googleapis.com/v2"
_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
# A transcript's entries are reliably complete only once the file is generated. ENDED means the
# session stopped but the file may still be assembling, so we wait for FILE_GENERATED.
_READY_STATES = {"FILE_GENERATED"}
# meet.google.com/abc-mnop-xyz  ->  "abc-mnop-xyz"
_CODE_RE = re.compile(r"meet\.google\.com/([a-z0-9-]+)", re.IGNORECASE)


def enabled() -> bool:
    """Global gate — per-user Google token is checked by the caller."""
    return bool(settings.meet_transcript_ingest)


def meeting_code(meeting_url: str) -> str | None:
    """Extract the Meet meeting code from a meeting URL, or None if it isn't a Meet link."""
    m = _CODE_RE.search(meeting_url or "")
    return m.group(1) if m else None


async def _get(client: httpx.AsyncClient, token: str, path: str, params: dict | None = None) -> dict | None:
    try:
        resp = await client.get(
            f"{_BASE}/{path}", params=params or {}, headers={"Authorization": f"Bearer {token}"}
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        # 403 = scope not granted / not a Workspace meeting; 404 = no such record. Both are
        # "nothing to ingest", logged quietly so a mis-scoped token doesn't spam errors.
        log.info("meet api %s -> %s", path, exc.response.status_code if exc.response else "?")
        return None
    except Exception as exc:  # pragma: no cover - network path
        log.info("meet api %s failed: %s", path, exc)
        return None


async def latest_conference_record(token: str, code: str) -> dict | None:
    """The most recent ENDED conference record for a meeting code, or None if none exists yet."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        data = await _get(client, token, "conferenceRecords", {"filter": f'space.meeting_code = "{code}"'})
    if not data:
        return None
    # Only ended conferences have a transcript to read; newest endTime wins.
    ended = [r for r in (data.get("conferenceRecords") or []) if r.get("endTime")]
    if not ended:
        return None
    ended.sort(key=lambda r: r.get("endTime", ""), reverse=True)
    return ended[0]


async def _resolve_participant(client: httpx.AsyncClient, token: str, name: str, cache: dict[str, str]) -> str:
    """participant resource name -> human display name (cached per fetch)."""
    if name in cache:
        return cache[name]
    data = await _get(client, token, name)  # name is already the full resource path
    label = "Speaker"
    if data:
        for key in ("signedinUser", "anonymousUser", "phoneUser"):
            u = data.get(key) or {}
            dn = (u.get("displayName") or "").strip()
            if dn:
                # A phoneUser displayName is a redacted number, not a name — keep but mark it.
                label = dn if key != "phoneUser" else f"Caller ({dn})"
                break
    cache[name] = label
    return label


async def fetch_transcript(token: str, conference_record_name: str) -> list[dict] | None:
    """Fetch the ready transcript for a conference record as ordered speaker/text segments.

    Returns None when no transcript is ready yet (still generating, or transcription was never
    enabled) so the caller retries later. Returns a (possibly empty) list once a transcript exists.
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        tdata = await _get(client, token, f"{conference_record_name}/transcripts")
        if tdata is None:
            return None
        ready = next(
            (t for t in (tdata.get("transcripts") or []) if t.get("state") in _READY_STATES),
            None,
        )
        if not ready:
            return None  # ENDED-but-not-generated, or no transcript at all → retry later

        segments: list[dict] = []
        cache: dict[str, str] = {}
        page_token: str | None = None
        while True:
            params = {"pageSize": 100}
            if page_token:
                params["pageToken"] = page_token
            edata = await _get(client, token, f"{ready['name']}/entries", params)
            if edata is None:
                break
            for e in edata.get("transcriptEntries") or []:
                text = (e.get("text") or "").strip()
                if not text:
                    continue
                speaker = await _resolve_participant(client, token, e.get("participant", ""), cache)
                segments.append({"speaker": speaker, "text": text, "start": e.get("startTime", "")})
            page_token = edata.get("nextPageToken")
            if not page_token:
                break
        return segments
