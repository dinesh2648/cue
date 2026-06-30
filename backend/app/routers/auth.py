"""Google sign-in — app login via Google OAuth, issuing our own session JWT.

Flow:
  1. Browser hits  GET /api/auth/google/login  → 302 to Google's consent screen.
  2. Google redirects back to  GET /api/auth/google/callback?code&state.
  3. We exchange the code, read the user's Google profile, upsert the user, mint a
     session JWT, and redirect to the frontend with the token in the URL fragment
     (`#token=…`, never sent to servers / logged).

Reuses the same Google OAuth app as the Drive/Gmail/Calendar connectors — just add
this callback URL to the app's authorized redirect URIs.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..security.auth import issue_session, now, session_key, upsert_user, verify_session

log = logging.getLogger("copilot.auth.google")
router = APIRouter(prefix="/api/auth", tags=["auth"])

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


def _redirect_uri() -> str:
    return f"{settings.app_base_url}/api/auth/google/callback"


@router.get("/google/login")
def google_login(next: str | None = Query(default=None)) -> RedirectResponse:
    """Send the browser to Google's consent screen."""
    if not settings.google_login_enabled:
        raise HTTPException(400, "Google login is not configured")
    state = jwt.encode(
        {"p": "login", "next": next or "/", "exp": now() + timedelta(minutes=10)},
        session_key(),
        algorithm="HS256",
    )
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
        "include_granted_scopes": "true",
    }
    return RedirectResponse(f"{_AUTH_URL}?{urlencode(params)}")


@router.get("/google/callback")
async def google_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Google redirect target: exchange the code, sign the user in, return to the app."""
    fe = settings.frontend_url.rstrip("/")
    if error or not code or not state:
        return RedirectResponse(f"{fe}/?auth_error={error or 'missing_code'}")
    try:
        claims = verify_session(state)  # same HS256 secret signs login state
        if claims.get("p") != "login":
            raise ValueError("bad purpose")
    except Exception:
        return RedirectResponse(f"{fe}/?auth_error=bad_state")

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            tok = await client.post(
                _TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": _redirect_uri(),
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                },
            )
            tok.raise_for_status()
            access = tok.json().get("access_token")
            info = await client.get(_USERINFO_URL, headers={"Authorization": f"Bearer {access}"})
            info.raise_for_status()
            profile = info.json()
    except Exception as exc:  # pragma: no cover - provider/network errors
        log.warning("google login exchange failed: %s", exc)
        return RedirectResponse(f"{fe}/?auth_error=google_exchange_failed")

    email = (profile.get("email") or "").lower()
    sub = profile.get("sub") or email
    if not sub:
        return RedirectResponse(f"{fe}/?auth_error=no_identity")
    # Require a Google-verified email — tenancy + RBAC are keyed on the email domain, so an
    # unverified address at someone's corporate domain must not be pooled into that tenant.
    if email and not profile.get("email_verified", False):
        return RedirectResponse(f"{fe}/?auth_error=email_unverified")
    name = profile.get("name") or (email.split("@")[0] if email else "User")

    user = upsert_user(db, f"google_{sub}", email, name)
    session = issue_session(user)
    nxt = claims.get("next") or "/"
    if not nxt.startswith("/"):
        nxt = "/"
    # Token in the URL fragment — the frontend reads it client-side and stores it.
    return RedirectResponse(f"{fe}{nxt}#token={session}")
