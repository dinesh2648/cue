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
from .routers import account, actions, ask, auth, billing, calendar, connectors, crm, knowledge, meetings, webhooks
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


def _check_production_secrets() -> None:
    """Fail fast in production: never run with the insecure dev signing/encryption key."""
    if settings.google_login_enabled:
        if not settings.session_secret and not settings.token_encryption_key:
            raise RuntimeError(
                "Refusing to start: Google login is enabled but SESSION_SECRET / "
                "TOKEN_ENCRYPTION_KEY are unset — session JWTs would use the insecure dev key. "
                "Set SESSION_SECRET and TOKEN_ENCRYPTION_KEY."
            )
        if not settings.token_encryption_key:
            log.warning("TOKEN_ENCRYPTION_KEY unset — connector tokens use a derived key; set it explicitly.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _check_production_secrets()
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

    # Auto-pilot loop (auto-join + auto-summarize). No-ops when no autopilot users / no Recall.
    import asyncio

    from . import autopilot

    ap_task = asyncio.create_task(autopilot.run_loop())
    try:
        yield
    finally:
        ap_task.cancel()


app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)

# Credentialed CORS can't use a wildcard origin — if someone sets CORS_ORIGINS=*,
# drop credentials rather than emit an invalid/unsafe policy.
_cors_origins = settings.cors_origin_list
_cors_credentials = "*" not in _cors_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_credentials,
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
    if len(_rate_window) > 10000:  # bound memory: drop only entries from past windows
        for k in [k for k, (w, _) in _rate_window.items() if w != window]:
            del _rate_window[k]
    win, count = _rate_window.get(ip, (window, 0))
    count = count + 1 if win == window else 1
    _rate_window[ip] = (window, count)
    if count > settings.rate_limit_per_minute:
        return JSONResponse({"detail": "Rate limit exceeded. Try again shortly."}, status_code=429)
    return await call_next(request)


app.include_router(account.router)
app.include_router(auth.router)
app.include_router(billing.router)
app.include_router(calendar.router)
app.include_router(connectors.router)
app.include_router(ask.router)
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
    # Authorize: the connecting user must be allowed to see this meeting (same RBAC as REST).
    db = SessionLocal()
    try:
        user = user_from_token(db, token)
        meeting = db.get(Meeting, meeting_id)
        if not settings.dev_mode:
            from .security.auth import visible_user_ids

            allowed = bool(
                user and meeting and (
                    meeting.owner_user_id in visible_user_ids(db, user)
                    or (user.email and user.email in (meeting.attendees or []))
                )
            )
            if not allowed:
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
