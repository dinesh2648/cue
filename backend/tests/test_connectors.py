"""Tests for the per-user connector security path (no live OAuth required)."""
from __future__ import annotations

import asyncio

import pytest

from app.connectors import manager
from app.connectors.registry import CONNECTORS, mcp_url
from app.db import SessionLocal, init_db
from app.models import ConnectorConnection, User
from app.security.crypto import decrypt, encrypt


def test_crypto_roundtrip():
    secret = "pat-na1-super-secret-token"
    assert decrypt(encrypt(secret)) == secret
    assert encrypt(None) is None
    assert decrypt(None) is None


def test_oauth_state_sign_verify():
    state = manager.sign_state("user_123", "hubspot")
    uid, provider = manager.verify_state(state)
    assert uid == "user_123"
    assert provider == "hubspot"


def test_catalog_lists_all_providers():
    init_db()
    db = SessionLocal()
    try:
        user = User(id="t_user", email="t@x.com")
        db.merge(user)
        db.commit()
        cat = manager.catalog(db, user)
        providers = {c["provider"] for c in cat}
        assert providers == set(CONNECTORS.keys())
        assert all(c["status"] == "disconnected" for c in cat)
    finally:
        db.close()


def test_active_mcp_servers_exposes_connected_only():
    init_db()
    db = SessionLocal()
    try:
        db.merge(User(id="u_mcp", email="u@x.com"))
        db.commit()
        # A connected provider with an MCP url + token → exposed.
        db.add(
            ConnectorConnection(
                user_id="u_mcp",
                provider="hubspot",
                status="connected",
                access_token_enc=encrypt("live-token-abc"),
                mcp_url=mcp_url("hubspot"),
            )
        )
        # A disconnected provider → never exposed.
        db.add(ConnectorConnection(user_id="u_mcp", provider="notion", status="disconnected"))
        db.commit()

        servers = asyncio.run(manager.active_mcp_servers(db, "u_mcp"))
        assert len(servers) == 1
        assert servers[0]["name"] == "hubspot"
        assert servers[0]["token"] == "live-token-abc"  # decrypted for the agent
        assert servers[0]["url"]
    finally:
        db.close()


def test_isolation_between_users():
    init_db()
    db = SessionLocal()
    try:
        db.merge(User(id="u_a", email="a@x.com"))
        db.add(
            ConnectorConnection(
                user_id="u_a", provider="hubspot", status="connected",
                access_token_enc=encrypt("a-token"), mcp_url=mcp_url("hubspot"),
            )
        )
        db.commit()
        # A different user sees none of u_a's connections.
        assert asyncio.run(manager.active_mcp_servers(db, "u_b")) == []
    finally:
        db.close()
