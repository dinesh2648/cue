"""WebSocket connection manager (per-meeting rooms).

In-process fan-out by default. To scale horizontally per the PRD (Redis Streams),
publish each event to a Redis stream keyed by meeting_id and have every API
replica subscribe — the `broadcast` call is the single integration point.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import WebSocket

log = logging.getLogger("copilot.ws")


class ConnectionManager:
    def __init__(self) -> None:
        self._rooms: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, meeting_id: str, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._rooms.setdefault(meeting_id, set()).add(ws)
        log.info("ws connected room=%s size=%d", meeting_id, len(self._rooms[meeting_id]))

    async def disconnect(self, meeting_id: str, ws: WebSocket) -> None:
        async with self._lock:
            room = self._rooms.get(meeting_id)
            if room:
                room.discard(ws)
                if not room:
                    self._rooms.pop(meeting_id, None)

    async def broadcast(self, meeting_id: str, event: dict) -> None:
        room = list(self._rooms.get(meeting_id, set()))
        dead: list[WebSocket] = []
        for ws in room:
            try:
                await ws.send_json(event)
            except Exception:  # client vanished
                dead.append(ws)
        for ws in dead:
            await self.disconnect(meeting_id, ws)


manager = ConnectionManager()
