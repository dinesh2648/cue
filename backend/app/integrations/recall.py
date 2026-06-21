"""Recall.ai meeting-bot integration (FR-001 real capture).

Sends a bot into a real Google Meet / Zoom / Teams call. The bot streams live
transcript segments to our webhook, which feeds the same `process_utterance`
pipeline the simulator uses — so the copilot works identically on real calls.

Requires RECALL_API_KEY. Without it, the simulator remains the capture source.
"""
from __future__ import annotations

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


def _webhook_url(meeting_id: str) -> str:
    return f"{settings.app_base_url}/api/webhooks/recall?meeting_id={meeting_id}"


async def create_bot(meeting_url: str, meeting_id: str, bot_name: str = "Sales Copilot") -> dict:
    """Dispatch a Recall bot to the meeting with real-time transcript → our webhook."""
    api_key = os.getenv("RECALL_API_KEY")
    if not api_key:
        raise RuntimeError("RECALL_API_KEY not configured")

    payload = {
        "meeting_url": meeting_url,
        "bot_name": bot_name,
        "recording_config": {
            # Use the meeting platform's live captions; swap in an ASR provider as needed.
            "transcript": {"provider": {"meeting_captions": {}}},
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
