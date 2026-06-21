"""Per-user connector lifecycle: connect (OAuth), store (encrypted), refresh,
disconnect, and expose each user's live remote-MCP servers to the agent.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import AuditLog, ConnectorConnection, User
from ..security.crypto import decrypt, encrypt
from . import oauth
from .registry import CONNECTORS, is_configured, mcp_url

log = logging.getLogger("copilot.connectors")

# 64-char (≥32 byte) HS256 secret derived from the configured key.
_STATE_SECRET = hashlib.sha256(
    ((settings.token_encryption_key or "copilot-dev-insecure-key") + ":state").encode()
).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── OAuth state (stateless, signed) ──────────────────────────────────────────
def sign_state(user_id: str, provider: str) -> str:
    return jwt.encode(
        {"uid": user_id, "provider": provider, "exp": _now() + timedelta(minutes=10)},
        _STATE_SECRET,
        algorithm="HS256",
    )


def verify_state(state: str) -> tuple[str, str]:
    claims = jwt.decode(state, _STATE_SECRET, algorithms=["HS256"])
    return claims["uid"], claims["provider"]


# ── Catalog + status ─────────────────────────────────────────────────────────
def catalog(db: Session, user: User) -> list[dict]:
    conns = {
        c.provider: c
        for c in db.scalars(select(ConnectorConnection).where(ConnectorConnection.user_id == user.id))
    }
    out = []
    for key, c in CONNECTORS.items():
        conn = conns.get(key)
        out.append(
            {
                "provider": key,
                "name": c.name,
                "icon": c.icon,
                "category": c.category,
                "description": c.description,
                # OAuth is an optional admin convenience; users can always BYO-connect.
                "oauth_available": is_configured(key),
                "mcp_default": mcp_url(key) or "",
                "has_mcp": bool(mcp_url(key)),
                "status": conn.status if conn else "disconnected",
                "account_label": conn.account_label if conn else "",
                "error": conn.error if conn else None,
            }
        )
    return out


def _get(db: Session, user_id: str, provider: str) -> ConnectorConnection | None:
    return db.scalar(
        select(ConnectorConnection).where(
            ConnectorConnection.user_id == user_id, ConnectorConnection.provider == provider
        )
    )


# ── Connect / callback / disconnect ──────────────────────────────────────────
def authorize_url(user: User, provider: str) -> str:
    if provider not in CONNECTORS:
        raise ValueError("unknown provider")
    if not is_configured(provider):
        raise ValueError(f"{provider} OAuth client not configured (set {provider.upper()}_CLIENT_ID/SECRET)")
    return oauth.build_authorize_url(provider, sign_state(user.id, provider))


async def handle_callback(db: Session, provider: str, code: str, state: str) -> ConnectorConnection:
    user_id, expected = verify_state(state)
    if expected != provider:
        raise ValueError("state/provider mismatch")
    tok = await oauth.exchange_code(provider, code)

    conn = _get(db, user_id, provider) or ConnectorConnection(user_id=user_id, provider=provider)
    conn.access_token_enc = encrypt(tok["access_token"])
    if tok.get("refresh_token"):
        conn.refresh_token_enc = encrypt(tok["refresh_token"])
    conn.expires_at = _expiry(tok.get("expires_in"))
    conn.scopes = (tok.get("scope") or "").split() if tok.get("scope") else CONNECTORS[provider].oauth.scopes
    conn.account_label = tok.get("account_label", "")
    conn.mcp_url = mcp_url(provider)
    conn.status = "connected"
    conn.error = None
    db.add(conn)
    db.add(AuditLog(actor=user_id, action="connector.connected", resource=provider))
    db.commit()
    log.info("connected provider=%s user=%s", provider, user_id)
    return conn


def connect_with_token(
    db: Session,
    user_id: str,
    provider: str,
    token: str,
    mcp_url_override: str | None = None,
    account_label: str = "",
) -> ConnectorConnection:
    """Bring-your-own connection: the user supplies their own token (+ optional MCP URL).

    No admin OAuth-client registration required — this is the default self-service path.
    The token is the user's own credential, so access stays scoped to what they can see.
    """
    if provider not in CONNECTORS:
        raise ValueError("unknown provider")
    if not token.strip():
        raise ValueError("token is required")

    conn = _get(db, user_id, provider) or ConnectorConnection(user_id=user_id, provider=provider)
    conn.access_token_enc = encrypt(token.strip())
    conn.refresh_token_enc = None
    conn.expires_at = None
    conn.mcp_url = (mcp_url_override or "").strip() or mcp_url(provider)
    conn.account_label = account_label.strip() or "Connected"
    conn.scopes = []
    conn.status = "connected"
    conn.error = None
    db.add(conn)
    db.add(AuditLog(actor=user_id, action="connector.connected.byo", resource=provider))
    db.commit()
    log.info("BYO-connected provider=%s user=%s mcp=%s", provider, user_id, bool(conn.mcp_url))
    return conn


def disconnect(db: Session, user_id: str, provider: str) -> None:
    conn = _get(db, user_id, provider)
    if conn:
        conn.status = "disconnected"
        conn.access_token_enc = None
        conn.refresh_token_enc = None
        conn.expires_at = None
        db.add(AuditLog(actor=user_id, action="connector.disconnected", resource=provider))
        db.commit()


def _expiry(expires_in) -> datetime | None:
    try:
        return _now() + timedelta(seconds=int(expires_in)) if expires_in else None
    except (TypeError, ValueError):
        return None


# ── Token access for the agent ───────────────────────────────────────────────
async def _valid_access_token(db: Session, conn: ConnectorConnection) -> str | None:
    if conn.status != "connected":
        return None
    needs_refresh = conn.expires_at and _now() >= conn.expires_at - timedelta(seconds=60)
    if needs_refresh and conn.refresh_token_enc:
        try:
            tok = await oauth.refresh_token(conn.provider, decrypt(conn.refresh_token_enc) or "")
            if tok.get("access_token"):
                conn.access_token_enc = encrypt(tok["access_token"])
                if tok.get("refresh_token"):
                    conn.refresh_token_enc = encrypt(tok["refresh_token"])
                conn.expires_at = _expiry(tok.get("expires_in"))
                db.commit()
        except Exception as exc:  # pragma: no cover
            conn.status = "error"
            conn.error = f"refresh failed: {exc}"
            db.commit()
            return None
    return decrypt(conn.access_token_enc)


async def active_mcp_servers(db: Session, user_id: str) -> list[dict]:
    """The user's connected providers exposed as remote MCP servers for Claude.

    Returns [{name, url, token}] — only providers that are connected, have a token,
    and have an MCP endpoint. This is the live-federated, permission-scoped tool set.
    """
    servers: list[dict] = []
    conns = db.scalars(
        select(ConnectorConnection).where(
            ConnectorConnection.user_id == user_id, ConnectorConnection.status == "connected"
        )
    )
    for conn in conns:
        url = conn.mcp_url or mcp_url(conn.provider)
        if not url:
            continue
        token = await _valid_access_token(db, conn)
        if not token:
            continue
        servers.append({"name": conn.provider, "url": url, "token": token})
    return servers
