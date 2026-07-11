"""Per-user connector lifecycle: connect (OAuth), store (encrypted), refresh,
disconnect, and expose each user's live remote-MCP servers to the agent.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx
import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import AuditLog, ConnectorConnection, User
from ..security.crypto import decrypt, encrypt
from . import mcp_oauth, oauth
from .registry import CONNECTORS, is_configured, mcp_url, redirect_uri

log = logging.getLogger("copilot.connectors")

# 64-char (≥32 byte) HS256 secret derived from the configured key.
_STATE_SECRET = hashlib.sha256(
    ((settings.token_encryption_key or "copilot-dev-insecure-key") + ":state").encode()
).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── OAuth state (stateless, signed) ──────────────────────────────────────────
def sign_state(user_id: str, provider: str, code_verifier: str | None = None,
               extra: dict | None = None) -> str:
    payload = {"uid": user_id, "provider": provider, "exp": _now() + timedelta(minutes=10)}
    if code_verifier:  # carry the PKCE verifier through the round-trip (signed, tamper-proof)
        payload["cv"] = code_verifier
    if extra:  # DCR context (dynamic client_id, token endpoint, resource) — signed, tamper-proof
        payload.update(extra)
    return jwt.encode(payload, _STATE_SECRET, algorithm="HS256")


def verify_state(state: str) -> tuple[str, str, str | None]:
    claims = jwt.decode(state, _STATE_SECRET, algorithms=["HS256"])
    return claims["uid"], claims["provider"], claims.get("cv")


def decode_state(state: str) -> dict:
    """Full signed-state claims (incl. DCR context) for the OAuth callback."""
    return jwt.decode(state, _STATE_SECRET, algorithms=["HS256"])


# ── Health (why isn't this working?) ─────────────────────────────────────────
# Write scopes a connector needs for its actions; if the granted scopes are known and this is
# absent, the connection is "limited" (reads work, writes will 401 until the user reconnects).
_WRITE_SCOPES = {
    "gmail": ("https://www.googleapis.com/auth/gmail.compose", "send & draft email"),
    "google_calendar": ("https://www.googleapis.com/auth/calendar.events", "create events"),
}


def _is_demo_token(conn: ConnectorConnection) -> bool:
    if not conn.access_token_enc:
        return False
    try:
        tok = decrypt(conn.access_token_enc)
    except Exception:  # pragma: no cover - corrupt ciphertext
        return False
    return bool(tok and tok.startswith("demo-"))


def connection_health(conn: ConnectorConnection | None) -> tuple[str, str]:
    """Verdict about a connection WITHOUT a network call, from stored state alone.

    Returns (health, reason). health ∈ healthy | limited | expired | error | demo | disconnected.
    'reason' is a user-facing one-liner that says how to fix it (empty when healthy).
    """
    if conn is None or conn.status == "disconnected":
        return "disconnected", ""
    if conn.status == "error":
        return "error", conn.error or "Something went wrong — reconnect this tool."
    if _is_demo_token(conn):
        return "demo", "Demo connection — connect your real account to answer from live data."
    exp = conn.expires_at
    if exp is not None and exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp is not None and _now() >= exp and not conn.refresh_token_enc:
        return "expired", "Access expired — reconnect to refresh it."
    req = _WRITE_SCOPES.get(conn.provider)
    if req and conn.scopes and req[0] not in conn.scopes:
        return "limited", f"Connected for reading only — reconnect to grant permission to {req[1]}."
    return "healthy", ""


# ── Catalog + status ─────────────────────────────────────────────────────────
def catalog(db: Session, user: User) -> list[dict]:
    conns = {
        c.provider: c
        for c in db.scalars(select(ConnectorConnection).where(ConnectorConnection.user_id == user.id))
    }
    out = []
    for key, c in CONNECTORS.items():
        conn = conns.get(key)
        health, reason = connection_health(conn)
        out.append(
            {
                "provider": key,
                "name": c.name,
                "icon": c.icon,
                "category": c.category,
                "description": c.description,
                # OAuth is an optional admin convenience; users can always BYO-connect.
                # DCR connectors (e.g. Jira) do live one-click OAuth with no app setup.
                "oauth_available": is_configured(key) or (c.dcr and bool(mcp_url(key))),
                "oauth_mode": "live" if (is_configured(key) or (c.dcr and bool(mcp_url(key)))) else "demo",
                "mcp_default": mcp_url(key) or "",
                "has_mcp": bool(mcp_url(key)),
                "status": conn.status if conn else "disconnected",
                "account_label": conn.account_label if conn else "",
                "error": conn.error if conn else None,
                "health": health,
                "health_reason": reason,
                "can_test": bool(conn and conn.status != "disconnected"),
            }
        )
    return out


def _get(db: Session, user_id: str, provider: str) -> ConnectorConnection | None:
    return db.scalar(
        select(ConnectorConnection).where(
            ConnectorConnection.user_id == user_id, ConnectorConnection.provider == provider
        )
    )


def get_connection(db: Session, user_id: str, provider: str) -> ConnectorConnection | None:
    """Public accessor for an existing connection (any status)."""
    return _get(db, user_id, provider)


# ── Connect / callback / disconnect ──────────────────────────────────────────
async def authorize_url(user: User, provider: str) -> tuple[str, str]:
    """Return (authorize_url, mode). 'live' = real provider OAuth; 'demo' = built-in consent.

    DCR providers (e.g. Jira) connect one-click with no pre-registered app: we discover the
    MCP server's OAuth metadata, dynamically register a public client, and run PKCE.
    """
    if provider not in CONNECTORS:
        raise ValueError("unknown provider")
    conn = CONNECTORS[provider]

    # One-click MCP OAuth via Dynamic Client Registration (no ATLASSIAN_CLIENT_ID needed).
    if conn.dcr and mcp_url(provider):
        try:
            meta = await mcp_oauth.discover(mcp_url(provider))
            if mcp_oauth.supports_dcr(meta):
                scope = " ".join(conn.oauth.scopes)
                reg = await mcp_oauth.register_client(meta["registration_endpoint"], redirect_uri(provider), scope)
                verifier = oauth.new_code_verifier()
                state = sign_state(
                    user.id, provider, verifier,
                    extra={"cid": reg["client_id"], "cs": reg.get("client_secret"),
                           "te": meta["token_endpoint"], "res": mcp_url(provider)},
                )
                url = mcp_oauth.build_authorize_url(
                    meta, reg["client_id"], redirect_uri(provider), scope,
                    state, oauth.code_challenge(verifier), mcp_url(provider),
                )
                return url, "live"
        except Exception as exc:  # discovery/registration failed → fall through to static/demo
            log.warning("DCR connect for %s failed, falling back: %s", provider, exc)

    if is_configured(provider):
        verifier = oauth.new_code_verifier() if conn.oauth.pkce else None
        state = sign_state(user.id, provider, verifier)
        challenge = oauth.code_challenge(verifier) if verifier else None
        return oauth.build_authorize_url(provider, state, challenge), "live"
    state = sign_state(user.id, provider)
    return f"{settings.app_base_url}/api/connectors/{provider}/demo-authorize?state={quote(state)}", "demo"


def connect_demo(db: Session, provider: str, state: str) -> ConnectorConnection:
    """Complete the demo consent flow — stores a placeholder connection for that user.

    Demonstrates the exact OAuth click-through UX without registering a real app. Swaps
    automatically to live provider OAuth once the provider's client id/secret is set.
    """
    if provider not in CONNECTORS:
        raise ValueError("unknown provider")
    user_id, expected, _cv = verify_state(state)
    if expected != provider:
        raise ValueError("state/provider mismatch")
    conn = _get(db, user_id, provider) or ConnectorConnection(user_id=user_id, provider=provider)
    conn.access_token_enc = encrypt(f"demo-{provider}-token")
    conn.refresh_token_enc = None
    conn.expires_at = None
    conn.mcp_url = mcp_url(provider)
    conn.account_label = "Demo connection (your account)"
    conn.scopes = []
    conn.status = "connected"
    conn.error = None
    db.add(conn)
    db.add(AuditLog(actor=user_id, action="connector.connected.demo", resource=provider))
    db.commit()
    return conn


async def handle_callback(db: Session, provider: str, code: str, state: str) -> ConnectorConnection:
    claims = decode_state(state)
    user_id, expected, code_verifier = claims["uid"], claims["provider"], claims.get("cv")
    if expected != provider:
        raise ValueError("state/provider mismatch")

    oauth_meta: dict = {}
    if claims.get("te"):  # DCR path — exchange at the dynamically-discovered token endpoint
        tok = await mcp_oauth.exchange_code(
            claims["te"], claims["cid"], claims.get("cs"),
            code, code_verifier, redirect_uri(provider), claims["res"],
        )
        oauth_meta = {
            "client_id": claims["cid"], "client_secret": claims.get("cs"),
            "token_endpoint": claims["te"], "resource": claims["res"],
        }
    else:  # static provider OAuth
        tok = await oauth.exchange_code(provider, code, code_verifier)

    conn = _get(db, user_id, provider) or ConnectorConnection(user_id=user_id, provider=provider)
    conn.access_token_enc = encrypt(tok["access_token"])
    if tok.get("refresh_token"):
        conn.refresh_token_enc = encrypt(tok["refresh_token"])
    conn.expires_at = _expiry(tok.get("expires_in"))
    conn.scopes = (tok.get("scope") or "").split() if tok.get("scope") else CONNECTORS[provider].oauth.scopes
    conn.account_label = tok.get("account_label", "") or ("Connected (your account)" if oauth_meta else "")
    conn.mcp_url = mcp_url(provider)
    conn.oauth_meta = oauth_meta
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
    # SQLite returns naive datetimes even for tz-aware columns — normalize to UTC
    # before comparing against the tz-aware now().
    exp = conn.expires_at
    if exp is not None and exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    # Refresh proactively 5 min before expiry (not the last 60s) so a call never lands on a
    # just-expired token. Long-term validity comes from the refresh token staying alive — see
    # the OAuth-consent-screen note in docs; refreshing more often does NOT extend it.
    needs_refresh = exp is not None and _now() >= exp - timedelta(minutes=5)
    if needs_refresh and conn.refresh_token_enc:
        try:
            meta = conn.oauth_meta or {}
            if meta.get("token_endpoint"):  # DCR connection — refresh at its own endpoint
                tok = await mcp_oauth.refresh(
                    meta["token_endpoint"], meta["client_id"], meta.get("client_secret"),
                    decrypt(conn.refresh_token_enc) or "", meta.get("resource"),
                )
            else:
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


async def get_access_token(db: Session, user_id: str, provider: str) -> str | None:
    """A user's current (auto-refreshed) access token for a provider, or None.

    For direct provider REST calls (e.g. reading Google Calendar events) — separate
    from the MCP path. Returns None if not connected or the token can't be refreshed.
    """
    conn = _get(db, user_id, provider)
    if conn is None:
        return None
    return await _valid_access_token(db, conn)


async def inprocess_read_tokens(db: Session, user_id: str | None) -> dict[str, str | None]:
    """Live tokens for sources read IN-PROCESS (no usable hosted MCP): Google Drive, Gmail, Slack.
    The agent reads these via each REST API + the user's token. None when absent/demo."""
    keys = ("google_drive", "gmail", "slack")
    if not user_id:
        return {k: None for k in keys}

    async def _live(provider: str) -> str | None:
        t = await get_access_token(db, user_id, provider)
        return None if (not t or t.startswith("demo-")) else t

    return {k: await _live(k) for k in keys}


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
        transport = CONNECTORS[conn.provider].mcp_transport if conn.provider in CONNECTORS else "http"
        # Notion via a static PAT must be read IN-PROCESS (its hosted MCP rejects PATs); via a
        # DCR OAuth token it works as a normal remote MCP server. Flag it so the agents route
        # each correctly. Other providers are always remote.
        inprocess = conn.provider == "notion" and not (conn.oauth_meta or {}).get("token_endpoint")
        servers.append({
            "name": conn.provider, "url": url, "token": token,
            "transport": transport, "inprocess": inprocess,
        })
    return servers


# ── Active connection test ("Test" button) ───────────────────────────────────
async def _ping(provider: str, token: str) -> tuple[bool, str]:
    """Cheapest possible authenticated call to prove the token still works.

    Returns (ok, detail). ok=None-style handling isn't used — a provider with no test
    endpoint is treated by the caller as 'can't actively verify' via the returned detail.
    """
    conn = CONNECTORS.get(provider)
    url = conn.oauth.userinfo_url if conn else None
    if not url:
        return True, "no-test-endpoint"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            if provider == "hubspot":
                # HubSpot verifies a token by path, not Authorization header.
                resp = await client.get(url + token)
            else:
                resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
        if provider == "slack":
            # Slack always returns 200; the truth is in the JSON `ok` field.
            data = resp.json()
            return (bool(data.get("ok")), "" if data.get("ok") else str(data.get("error", "invalid_auth")))
        if resp.status_code in (401, 403):
            return False, "token rejected"
        if resp.status_code >= 400:
            return False, f"HTTP {resp.status_code}"
        return True, ""
    except Exception as exc:  # pragma: no cover - network
        return False, f"unreachable: {str(exc)[:100]}"


async def check_connection(db: Session, user_id: str, provider: str) -> dict:
    """Actively test a connection and reconcile stored status. Returns {ok, status, health, reason}."""
    if provider not in CONNECTORS:
        return {"ok": False, "status": "unknown", "health": "error", "reason": "Unknown provider."}
    conn = _get(db, user_id, provider)
    if conn is None or conn.status == "disconnected":
        return {"ok": False, "status": "disconnected", "health": "disconnected", "reason": "Not connected."}
    token = await _valid_access_token(db, conn)
    if not token:
        health, reason = connection_health(conn)
        return {"ok": False, "status": conn.status, "health": health if health != "healthy" else "error",
                "reason": reason or "No valid token — reconnect this tool."}
    if token.startswith("demo-"):
        return {"ok": True, "status": "connected", "health": "demo",
                "reason": "Demo connection — connect your real account to answer from live data."}

    ok, detail = await _ping(provider, token)
    if detail == "no-test-endpoint":
        health, reason = connection_health(conn)
        return {"ok": health in ("healthy", "limited"), "status": conn.status, "health": health,
                "reason": reason or "Connected. (No live test available for this provider.)"}
    if ok:
        if conn.status != "connected" or conn.error:  # recovered — clear the stale error
            conn.status, conn.error = "connected", None
            db.commit()
        health, reason = connection_health(conn)
        return {"ok": True, "status": "connected", "health": health,
                "reason": reason or "Working — the copilot can read this as you."}
    # failed — record it so the catalog reflects the problem next load
    conn.status = "error"
    conn.error = f"Test failed: {detail}. Reconnect to fix."
    db.commit()
    return {"ok": False, "status": "error", "health": "error", "reason": conn.error}
