"""Connector API — per-employee OAuth connect/disconnect for HubSpot/Drive/Gmail/Notion."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import settings
from ..connectors import manager
from ..db import get_db
from ..models import User
from ..security.auth import get_current_user

log = logging.getLogger("copilot.connectors.api")
router = APIRouter(prefix="/api/connectors", tags=["connectors"])


@router.get("")
def list_connectors(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    return manager.catalog(db, user)


class TokenConnectRequest(BaseModel):
    token: str
    mcp_url: str | None = None
    account_label: str = ""


@router.post("/{provider}/connect-token")
def connect_token(
    provider: str,
    body: TokenConnectRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Bring-your-own connection: the user connects with their own token (+ optional MCP URL).

    The default self-service path — no admin OAuth-client registration needed.
    """
    try:
        conn = manager.connect_with_token(
            db, user.id, provider, body.token, body.mcp_url, body.account_label
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "status": conn.status, "has_mcp": bool(conn.mcp_url)}


@router.get("/{provider}/connect")
def connect(provider: str, user: User = Depends(get_current_user)) -> dict:
    """Optional OAuth path (only when an admin has registered the provider's OAuth client)."""
    try:
        return {"authorize_url": manager.authorize_url(user, provider)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/{provider}/callback")
async def callback(
    provider: str,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """OAuth redirect target (browser). Exchanges the code, stores tokens, returns to the UI."""
    base = f"{settings.frontend_url}/connections"
    if error or not code or not state:
        return RedirectResponse(f"{base}?error={error or 'missing_code'}")
    try:
        await manager.handle_callback(db, provider, code, state)
        return RedirectResponse(f"{base}?connected={provider}")
    except Exception as exc:  # pragma: no cover - provider/network errors
        log.warning("oauth callback failed provider=%s: %s", provider, exc)
        return RedirectResponse(f"{base}?error=connect_failed")


@router.post("/{provider}/disconnect")
def disconnect(provider: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    manager.disconnect(db, user.id, provider)
    return {"ok": True}
