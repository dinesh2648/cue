"""FastAPI application entrypoint."""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from .config import settings
from .db import SessionLocal, init_db
from .knowledge.store import index
from .models import KnowledgeDoc, Meeting, Suggestion
from .realtime.engine import process_utterance
from .realtime.manager import manager
from .routers import account, actions, billing, connectors, crm, knowledge, meetings, webhooks
from .security.auth import user_from_token
from .seed.data import seed_if_empty

if settings.sentry_dsn:  # optional error tracking
    try:
        import sentry_sdk

        sentry_sdk.init(dsn=settings.sentry_dsn, traces_sample_rate=0.1)
    except ImportError:
        logging.getLogger("copilot").warning("SENTRY_DSN set but sentry-sdk not installed")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("copilot")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        counts = seed_if_empty(db)
        docs = db.scalars(select(KnowledgeDoc)).all()
        doc_dicts = [
            {"id": d.id, "title": d.title, "doc_type": d.doc_type, "url": d.url, "content": d.content}
            for d in docs
        ]
    finally:
        db.close()

    await index.build(doc_dicts)
    log.info(
        "Ready — seeded %s, knowledge index backend=%s (%d chunks), LLM=%s",
        counts,
        index.mode,
        len(index.chunks),
        settings.llm_provider,
    )
    yield


app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_rate_window: dict[str, tuple[int, int]] = {}


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    """Basic per-IP fixed-window rate limit. Use Redis for multi-instance deployments."""
    path = request.url.path
    if path in ("/health", "/metrics") or path.startswith("/ws"):
        return await call_next(request)
    ip = request.client.host if request.client else "anon"
    window = int(time.time() // 60)
    win, count = _rate_window.get(ip, (window, 0))
    count = count + 1 if win == window else 1
    _rate_window[ip] = (window, count)
    if count > settings.rate_limit_per_minute:
        return JSONResponse({"detail": "Rate limit exceeded. Try again shortly."}, status_code=429)
    return await call_next(request)


app.include_router(account.router)
app.include_router(billing.router)
app.include_router(connectors.router)
app.include_router(actions.router)
app.include_router(meetings.router)
app.include_router(knowledge.router)
app.include_router(crm.router)
app.include_router(webhooks.router)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "version": settings.version,
        "llm_provider": settings.llm_provider,
        "agent_engine": settings.resolved_agent_engine,
        "knowledge_backend": index.mode,
        "dev_mode": settings.dev_mode,
    }


@app.get("/metrics")
def metrics() -> dict:
    """Live KPIs against the PRD success metrics."""
    db = SessionLocal()
    try:
        latencies = sorted(db.scalars(select(Suggestion.latency_ms)).all())
        n = len(latencies)
        avg = round(sum(latencies) / n, 1) if n else 0.0
        p95 = latencies[int(0.95 * (n - 1))] if n else 0
        sla_ms = settings.response_sla_seconds * 1000
        within = sum(1 for x in latencies if x <= sla_ms)
        return {
            "meetings": db.scalar(select(func.count()).select_from(Meeting)) or 0,
            "suggestions": n,
            "avg_latency_ms": avg,
            "p95_latency_ms": p95,
            "response_sla_ms": sla_ms,
            "sla_compliance_pct": round(100 * within / n, 1) if n else 100.0,
        }
    finally:
        db.close()


@app.websocket("/ws/meetings/{meeting_id}")
async def meeting_ws(ws: WebSocket, meeting_id: str, token: str | None = Query(default=None)) -> None:
    # Authorize: the connecting user must own the meeting (lenient in DEV mode).
    db = SessionLocal()
    try:
        user = user_from_token(db, token)
        meeting = db.get(Meeting, meeting_id)
        if not settings.dev_mode:
            if user is None or (meeting and meeting.owner_user_id and meeting.owner_user_id != user.id):
                await ws.close(code=4403)
                return
    finally:
        db.close()

    await manager.connect(meeting_id, ws)
    try:
        while True:
            msg = await ws.receive_json()
            # Optional interactive input: type as the customer over the socket.
            if isinstance(msg, dict) and msg.get("type") == "utterance":
                await process_utterance(
                    meeting_id,
                    msg.get("speaker", "Customer"),
                    msg.get("role", "customer"),
                    msg.get("text", ""),
                )
    except WebSocketDisconnect:
        await manager.disconnect(meeting_id, ws)
    except Exception:  # pragma: no cover
        await manager.disconnect(meeting_id, ws)
