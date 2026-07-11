"""Connector API — per-employee OAuth connect/disconnect for HubSpot/Drive/Gmail/Notion."""
from __future__ import annotations

import logging

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..billing import service as billing_service
from ..config import settings
from ..connectors import manager
from ..connectors.registry import CONNECTORS
from ..db import get_db
from ..models import Organization, User
from ..security.auth import get_current_org, get_current_user

_CONN_LIMIT_MSG = "Connector limit reached for your plan. Upgrade to connect more tools."

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
    org: Organization = Depends(get_current_org),
    db: Session = Depends(get_db),
) -> dict:
    """Bring-your-own connection: the user connects with their own token (+ optional MCP URL).

    The default self-service path — no admin OAuth-client registration needed.
    """
    if manager.get_connection(db, user.id, provider) is None and not billing_service.within_connector_limit(db, user.id, org):
        raise HTTPException(402, _CONN_LIMIT_MSG)
    try:
        conn = manager.connect_with_token(
            db, user.id, provider, body.token, body.mcp_url, body.account_label
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "status": conn.status, "has_mcp": bool(conn.mcp_url)}


class CustomMcpRequest(BaseModel):
    name: str
    mcp_url: str
    token: str = ""
    transport: str = "http"  # "http" | "sse"
    category: str = "Custom"
    icon: str = "🧩"


@router.post("/custom")
def add_custom_mcp(
    body: CustomMcpRequest,
    user: User = Depends(get_current_user),
    org: Organization = Depends(get_current_org),
    db: Session = Depends(get_db),
) -> dict:
    """Point Cue at ANY remote MCP server — the whole MCP ecosystem, not just the built-in catalog.

    It then flows through the same path as a built-in connector: the agent's live tools, health,
    role-scoping and disconnect. Counts toward the plan's connector limit like any connection.
    """
    if not billing_service.within_connector_limit(db, user.id, org):
        raise HTTPException(402, _CONN_LIMIT_MSG)
    try:
        conn = manager.add_custom_mcp(
            db, user.id, name=body.name, mcp_url=body.mcp_url, token=body.token,
            transport=body.transport, category=body.category, icon=body.icon,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "provider": conn.provider, "status": conn.status, "has_mcp": bool(conn.mcp_url)}


@router.get("/{provider}/connect")
async def connect(
    provider: str,
    user: User = Depends(get_current_user),
    org: Organization = Depends(get_current_org),
    db: Session = Depends(get_db),
) -> dict:
    """Primary path: returns the provider's OAuth consent URL (the client redirects to it).

    `mode` is 'live' (real provider OAuth, incl. DCR one-click) or 'demo' (built-in screen).
    """
    if manager.get_connection(db, user.id, provider) is None and not billing_service.within_connector_limit(db, user.id, org):
        raise HTTPException(402, _CONN_LIMIT_MSG)
    try:
        url, mode = await manager.authorize_url(user, provider)
        return {"authorize_url": url, "mode": mode}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/{provider}/demo-authorize", response_class=HTMLResponse)
def demo_authorize(provider: str, state: str = Query(...)) -> HTMLResponse:
    """A simulated provider consent screen so the OAuth click-through works with zero setup."""
    if provider not in CONNECTORS:
        return HTMLResponse("Unknown provider", status_code=404)
    c = CONNECTORS[provider]
    approve = f"{settings.app_base_url}/api/connectors/{provider}/callback?demo=1&state={quote(state)}"
    deny = f"{settings.frontend_url}/connections?error=denied"
    scopes = "".join(f"<li>Read your {c.name} {s}</li>" for s in ["data the rep can access"])
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Authorize Sales Copilot · {c.name}</title>
<style>
  body{{margin:0;font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;
    background:#0b0f1a;color:#e8edf7;display:grid;place-items:center;min-height:100vh;padding:24px}}
  .box{{background:#151b2d;border:1px solid #26304a;border-radius:18px;max-width:420px;width:100%;
    padding:28px;box-shadow:0 20px 60px rgba(0,0,0,.5)}}
  .row{{display:flex;align-items:center;justify-content:center;gap:14px;margin-bottom:18px}}
  .ic{{width:52px;height:52px;border-radius:13px;display:grid;place-items:center;font-size:26px;background:#1b2336;border:1px solid #26304a}}
  .arrow{{color:#67738f;font-size:20px}}
  .ic.app{{background:linear-gradient(135deg,#6d7cff,#a855f7);border:none}}
  h1{{font-size:18px;text-align:center;margin:0 0 6px;letter-spacing:-.01em}}
  p.s{{text-align:center;color:#9aa7c4;font-size:13.5px;margin:0 0 18px;line-height:1.5}}
  .scopes{{background:#0f1422;border:1px solid #26304a;border-radius:11px;padding:14px 16px;margin:0 0 20px}}
  .scopes b{{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:#67738f}}
  ul{{margin:8px 0 0;padding-left:18px;color:#cdd6ea;font-size:13.5px;line-height:1.7}}
  .btns{{display:flex;gap:10px}}
  a.btn{{flex:1;text-align:center;text-decoration:none;padding:12px;border-radius:11px;font-weight:700;font-size:14px}}
  a.approve{{background:linear-gradient(135deg,#6d7cff,#a855f7);color:#fff}}
  a.deny{{background:#1b2336;border:1px solid #313c5c;color:#cdd6ea}}
  .note{{text-align:center;color:#67738f;font-size:11.5px;margin-top:16px}}
</style></head><body>
  <div class="box">
    <div class="row"><span class="ic">{c.icon}</span><span class="arrow">←</span><span class="ic app">🛰️</span></div>
    <h1>Sales Copilot wants to access your {c.name}</h1>
    <p class="s">Connecting as <b>you</b> — the copilot will only ever read what your {c.name}
      account can already see. You can disconnect anytime.</p>
    <div class="scopes"><b>This will allow Sales Copilot to</b><ul>{scopes}</ul></div>
    <div class="btns">
      <a class="btn deny" href="{deny}">Cancel</a>
      <a class="btn approve" href="{approve}">Allow access</a>
    </div>
    <div class="note">Demo authorization — simulates {c.name}'s real OAuth consent screen.</div>
  </div>
</body></html>"""
    return HTMLResponse(html)


@router.get("/{provider}/callback")
async def callback(
    provider: str,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    demo: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """OAuth redirect target (browser). Exchanges the code, stores the token, returns to the UI."""
    base = f"{settings.frontend_url}/connections"
    if error or not state:
        return RedirectResponse(f"{base}?error={error or 'missing_state'}")
    try:
        if demo == "1":
            manager.connect_demo(db, provider, state)
        else:
            if not code:
                return RedirectResponse(f"{base}?error=missing_code")
            await manager.handle_callback(db, provider, code, state)
        return RedirectResponse(f"{base}?connected={provider}")
    except Exception as exc:  # pragma: no cover - provider/network errors
        log.warning("oauth callback failed provider=%s: %s", provider, exc)
        return RedirectResponse(f"{base}?error=connect_failed")


@router.post("/{provider}/check")
async def check(provider: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Actively test a connection (cheap authenticated ping) and reconcile its stored status.

    Powers the 'Test' button — turns 'connected but silently broken' into a clear, fixable state.
    """
    if provider not in CONNECTORS:
        raise HTTPException(404, "Unknown provider")
    return await manager.check_connection(db, user.id, provider)


@router.post("/{provider}/disconnect")
def disconnect(provider: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    manager.disconnect(db, user.id, provider)
    return {"ok": True}
