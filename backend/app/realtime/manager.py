"""WebSocket connection manager (per-meeting rooms, user-aware).

In-process fan-out by default. To scale horizontally per the PRD (Redis Streams), publish each
event to a Redis stream keyed by meeting_id and have every API replica subscribe — `broadcast`
and `send_to_user` are the single integration points.

Each connection carries its user_id, so shared events (transcript, status, insights) broadcast to
the whole room, while personalized events (a user's own copilot suggestions) route only to that
user's socket(s).
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import WebSocket

log = logging.getLogger("copilot.ws")


class ConnectionManager:
    def __init__(self) -> None:
        # meeting_id -> {WebSocket: user_id|None}
        self._rooms: dict[str, dict[WebSocket, str | None]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, meeting_id: str, ws: WebSocket, user_id: str | None = None) -> None:
        await ws.accept()
        async with self._lock:
            self._rooms.setdefault(meeting_id, {})[ws] = user_id
        log.info("ws connected room=%s user=%s size=%d", meeting_id, user_id or "-", len(self._rooms[meeting_id]))

    async def disconnect(self, meeting_id: str, ws: WebSocket) -> None:
        async with self._lock:
            room = self._rooms.get(meeting_id)
            if room is not None:
                room.pop(ws, None)
                if not room:
                    self._rooms.pop(meeting_id, None)

    def subscriber_ids(self, meeting_id: str) -> set[str]:
        """Distinct user_ids currently connected to this meeting (for per-user answer fan-out)."""
        return {uid for uid in self._rooms.get(meeting_id, {}).values() if uid}

    async def broadcast(self, meeting_id: str, event: dict) -> None:
        """Shared event → everyone in the room (transcript, status, insights, summary)."""
        items = list(self._rooms.get(meeting_id, {}).items())
        dead: list[WebSocket] = []
        for ws, _uid in items:
            try:
                await ws.send_json(event)
            except Exception:  # client vanished
                dead.append(ws)
        for ws in dead:
            await self.disconnect(meeting_id, ws)

    async def send_to_user(self, meeting_id: str, user_id: str | None, event: dict) -> None:
        """Personalized event → only this user's socket(s) in the room. No-op if they're not here."""
        if not user_id:
            return
        items = list(self._rooms.get(meeting_id, {}).items())
        dead: list[WebSocket] = []
        for ws, uid in items:
            if uid != user_id:
                continue
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(meeting_id, ws)


manager = ConnectionManager()
