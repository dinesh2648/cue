"""Generic OAuth 2.0 authorization-code flow (with optional PKCE), per connector."""
from __future__ import annotations

import base64
import hashlib
import logging
import secrets
from urllib.parse import urlencode

import httpx

from .registry import CONNECTORS, client_credentials, redirect_uri

log = logging.getLogger("copilot.oauth")
_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


# ── PKCE (RFC 7636) — required by some providers (e.g. HubSpot MCP apps) ──────
def new_code_verifier() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def build_authorize_url(provider: str, state: str, challenge: str | None = None) -> str:
    c = CONNECTORS[provider]
    client_id, _ = client_credentials(provider)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri(provider),
        "response_type": "code",
        "state": state,
        **c.oauth.extra_authorize_params,
    }
    if c.oauth.scopes:
        params["scope"] = " ".join(c.oauth.scopes)
    if c.oauth.pkce and challenge:
        params["code_challenge"] = challenge
        params["code_challenge_method"] = "S256"
    return f"{c.oauth.authorize_url}?{urlencode(params)}"


async def exchange_code(provider: str, code: str, code_verifier: str | None = None) -> dict:
    c = CONNECTORS[provider]
    client_id, client_secret = client_credentials(provider)
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri(provider),
    }
    if c.oauth.pkce and code_verifier:
        data["code_verifier"] = code_verifier
    headers = dict(c.oauth.token_headers)
    if c.oauth.token_auth == "basic":
        auth = (client_id, client_secret)
    else:
        auth = None
        data["client_id"] = client_id
        data["client_secret"] = client_secret

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(c.oauth.token_url, data=data, headers=headers, auth=auth)
        resp.raise_for_status()
        tok = resp.json()
        label = await _account_label(client, provider, tok)
    return _normalize(tok, label)


async def refresh_token(provider: str, refresh: str) -> dict:
    c = CONNECTORS[provider]
    if not c.oauth.refreshable:
        return {}
    client_id, client_secret = client_credentials(provider)
    data = {"grant_type": "refresh_token", "refresh_token": refresh}
    if c.oauth.token_auth != "basic":
        data["client_id"] = client_id
        data["client_secret"] = client_secret
        auth = None
    else:
        auth = (client_id, client_secret)
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(c.oauth.token_url, data=data, auth=auth)
        resp.raise_for_status()
        return _normalize(resp.json(), None)


def _normalize(tok: dict, label: str | None) -> dict:
    access = tok.get("access_token")
    scope = tok.get("scope", "")
    # Slack's oauth.v2.access returns the USER token nested under authed_user (user_scope flow);
    # prefer it so the agent reads as the user (search, channel history) rather than as a bot.
    au = tok.get("authed_user") or {}
    if au.get("access_token"):
        access = au["access_token"]
        scope = au.get("scope", scope)
    return {
        "access_token": access,
        "refresh_token": tok.get("refresh_token") or au.get("refresh_token"),
        "expires_in": tok.get("expires_in") or au.get("expires_in"),
        "scope": scope,
        "account_label": label or "",
    }


async def _account_label(client: httpx.AsyncClient, provider: str, tok: dict) -> str:
    """Best-effort human label for the connected account (never fatal)."""
    try:
        c = CONNECTORS[provider]
        access = tok.get("access_token")
        if provider == "notion":
            return tok.get("workspace_name") or (tok.get("owner", {}) or {}).get("type", "Notion workspace")
        if provider == "hubspot" and access:
            r = await client.get(c.oauth.userinfo_url + access)
            r.raise_for_status()
            info = r.json()
            return info.get("hub_domain") or info.get("user") or "HubSpot account"
        if c.oauth.userinfo_url and access:  # google / linkedin (OIDC userinfo)
            r = await client.get(c.oauth.userinfo_url, headers={"Authorization": f"Bearer {access}"})
            r.raise_for_status()
            info = r.json()
            return info.get("email") or info.get("name") or f"{c.name} account"
    except Exception as exc:  # pragma: no cover
        log.info("account label lookup failed for %s: %s", provider, exc)
    return ""
