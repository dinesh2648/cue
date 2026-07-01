"""MCP OAuth with Dynamic Client Registration (DCR) — connect "like Claude", zero app setup.

For a remote MCP server that implements the MCP authorization spec (OAuth 2.1 + RFC 7591
DCR + RFC 8707 resource indicators), we:
  1. discover the authorization server's metadata from the MCP server's origin,
  2. dynamically register a public client (PKCE, no pre-created app),
  3. run the authorization-code + PKCE flow (the user just approves on the provider),
  4. exchange / refresh tokens at the discovered token endpoint.

Verified against Atlassian's remote MCP (mcp.atlassian.com). Providers whose MCP lacks a
registration_endpoint (e.g. GitHub) can't use this — they fall back to static OAuth / tokens.
"""
from __future__ import annotations

import logging
from urllib.parse import urlencode, urlsplit

import httpx

log = logging.getLogger("copilot.mcp_oauth")

_TIMEOUT = httpx.Timeout(20.0, connect=8.0)
_CLIENT_NAME = "Cue Copilot"


async def discover(mcp_url: str) -> dict:
    """Fetch the authorization-server metadata for an MCP server. Returns the AS metadata dict
    (authorization_endpoint, token_endpoint, registration_endpoint, scopes_supported)."""
    parts = urlsplit(mcp_url)
    origin = f"{parts.scheme}://{parts.netloc}"
    # RFC 8414: AS metadata at the origin's well-known. Try the path-scoped variant too.
    candidates = [
        f"{origin}/.well-known/oauth-authorization-server",
        f"{origin}/.well-known/oauth-authorization-server{parts.path.rstrip('/')}",
    ]
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as c:
        for url in candidates:
            try:
                r = await c.get(url)
                if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
                    meta = r.json()
                    if meta.get("authorization_endpoint") and meta.get("token_endpoint"):
                        return meta
            except Exception:  # pragma: no cover - try the next candidate
                continue
    raise RuntimeError(f"no OAuth authorization-server metadata for {mcp_url}")


def supports_dcr(meta: dict) -> bool:
    return bool(meta.get("registration_endpoint"))


async def register_client(registration_endpoint: str, redirect_uri: str, scope: str) -> dict:
    """RFC 7591 Dynamic Client Registration. Returns {client_id, client_secret?, ...}."""
    body = {
        "client_name": _CLIENT_NAME,
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",  # public client (PKCE) — no secret to leak
        "scope": scope,
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as c:
        r = await c.post(registration_endpoint, json=body)
        r.raise_for_status()
        data = r.json()
    if not data.get("client_id"):
        raise RuntimeError("DCR did not return a client_id")
    return data


def build_authorize_url(meta: dict, client_id: str, redirect_uri: str, scope: str,
                        state: str, challenge: str, resource: str) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "resource": resource,  # RFC 8707 — bind the token to this MCP server
    }
    return f"{meta['authorization_endpoint']}?{urlencode(params)}"


def _normalize(tok: dict) -> dict:
    return {
        "access_token": tok.get("access_token"),
        "refresh_token": tok.get("refresh_token"),
        "expires_in": tok.get("expires_in"),
        "scope": tok.get("scope"),
    }


async def exchange_code(token_endpoint: str, client_id: str, client_secret: str | None,
                        code: str, code_verifier: str, redirect_uri: str, resource: str) -> dict:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": code_verifier,
        "resource": resource,
    }
    if client_secret:
        data["client_secret"] = client_secret
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as c:
        r = await c.post(token_endpoint, data=data, headers={"Accept": "application/json"})
        r.raise_for_status()
        return _normalize(r.json())


async def refresh(token_endpoint: str, client_id: str, client_secret: str | None,
                  refresh_token: str, resource: str | None = None) -> dict:
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }
    if client_secret:
        data["client_secret"] = client_secret
    if resource:
        data["resource"] = resource
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as c:
        r = await c.post(token_endpoint, data=data, headers={"Accept": "application/json"})
        r.raise_for_status()
        return _normalize(r.json())
