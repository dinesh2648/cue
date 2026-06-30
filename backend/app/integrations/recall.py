"""Recall.ai meeting-bot integration (FR-001 real capture).

Sends a bot into a real Google Meet / Zoom / Teams call. The bot streams live
transcript segments to our webhook, which feeds the same `process_utterance`
pipeline the simulator uses — so the copilot works identically on real calls.

Requires RECALL_API_KEY. Without it, the simulator remains the capture source.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os

import httpx

from ..config import settings

log = logging.getLogger("copilot.recall")


def enabled() -> bool:
    return bool(os.getenv("RECALL_API_KEY"))


def _base_url() -> str:
    region = os.getenv("RECALL_REGION", "us-east-1")
    return f"https://{region}.recall.ai"


def webhook_token(meeting_id: str) -> str:
    """Per-meeting HMAC so the public Recall webhook can't be forged/replayed for other meetings."""
    secret = os.getenv("RECALL_WEBHOOK_SECRET") or settings.session_signing_secret
    return hmac.new(secret.encode(), meeting_id.encode(), hashlib.sha256).hexdigest()[:32]


def _public_base() -> str:
    """Public base URL Recall calls back on. Separate from APP_BASE_URL so OAuth redirects can
    use a stable localhost while the inbound webhook uses a public tunnel (set RECALL_PUBLIC_URL).
    """
    return (os.getenv("RECALL_PUBLIC_URL") or settings.app_base_url).rstrip("/")


def _webhook_url(meeting_id: str) -> str:
    return f"{_public_base()}/api/webhooks/recall?meeting_id={meeting_id}&token={webhook_token(meeting_id)}"


async def create_bot(meeting_url: str, meeting_id: str, bot_name: str | None = None) -> dict:
    """Dispatch a Recall bot to the meeting with real-time transcript → our webhook.

    The display name shown to participants when the bot joins is `bot_name`, defaulting to
    "AL Copilot" (override with the RECALL_BOT_NAME env var).
    """
    api_key = os.getenv("RECALL_API_KEY")
    if not api_key:
        raise RuntimeError("RECALL_API_KEY not configured")
    bot_name = bot_name or os.getenv("RECALL_BOT_NAME", "AL Copilot — Notetaker")

    # Transcription source — configurable so we can switch live without a code change.
    # "meeting_captions" (default) uses Google Meet's captions; set RECALL_TRANSCRIPT_PROVIDER
    # to an ASR provider (e.g. "assembly_ai_streaming", "deepgram_streaming") for reliable real-time.
    provider = os.getenv("RECALL_TRANSCRIPT_PROVIDER", "meeting_captions")
    payload = {
        "meeting_url": meeting_url,
        "bot_name": bot_name,
        "recording_config": {
            "transcript": {"provider": {provider: {}}},
            "realtime_endpoints": [
                {
                    "type": "webhook",
                    "url": _webhook_url(meeting_id),
                    "events": ["transcript.data"],
                }
            ],
        },
        "metadata": {"meeting_id": meeting_id},
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            f"{_base_url()}/api/v1/bot/",
            headers={"Authorization": f"Token {api_key}", "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        log.info("recall bot created id=%s meeting=%s", data.get("id"), meeting_id)
        return data


async def get_bot_status(bot_id: str) -> str | None:
    """Latest Recall bot status code (e.g. joining_call, in_waiting_room, call_ended, done)."""
    api_key = os.getenv("RECALL_API_KEY")
    if not api_key or not bot_id:
        return None
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{_base_url()}/api/v1/bot/{bot_id}/",
            headers={"Authorization": f"Token {api_key}"},
        )
        resp.raise_for_status()
        changes = resp.json().get("status_changes") or []
    return changes[-1].get("code") if changes else None


async def get_recording_url(bot_id: str) -> dict:
    """Fetch a bot's mixed-video recording. Returns {status, url}.

    The URL is a short-lived presigned S3 link, so we fetch it fresh on demand rather
    than storing it. status: done | processing | none | unavailable.
    """
    api_key = os.getenv("RECALL_API_KEY")
    if not api_key or not bot_id:
        return {"status": "unavailable", "url": None}
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(
            f"{_base_url()}/api/v1/bot/{bot_id}/",
            headers={"Authorization": f"Token {api_key}"},
        )
        resp.raise_for_status()
        data = resp.json()
    recordings = data.get("recordings") or []
    if not recordings:
        return {"status": "none", "url": None}
    rec = recordings[0]
    video = (rec.get("media_shortcuts") or {}).get("video_mixed") or {}
    url = (video.get("data") or {}).get("download_url")
    code = (video.get("status") or {}).get("code") or (rec.get("status") or {}).get("code")
    if url:
        return {"status": "done", "url": url}
    return {"status": code or "processing", "url": None}


def parse_transcript_event(body: dict) -> dict | None:
    """Normalize a Recall `transcript.data` webhook into {speaker, text, is_host}.

    Defensive across Recall payload shapes; returns None for non-transcript events
    or empty text.
    """
    if body.get("event") not in ("transcript.data", "transcript.partial_data", None):
        return None
    data = body.get("data", {}) or {}
    inner = data.get("data", data) or {}
    participant = inner.get("participant") or {}
    words = inner.get("words") or []
    text = " ".join(w.get("text", "") for w in words).strip() if words else (inner.get("text") or "").strip()
    if not text:
        return None
    return {
        "speaker": participant.get("name") or "Speaker",
        "is_host": bool(participant.get("is_host", False)),
        "text": text,
    }
