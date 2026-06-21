"""Authentication: Clerk session-JWT verification with a single-user DEV fallback.

When Clerk is configured, every request must carry a `Authorization: Bearer <jwt>`;
the token is verified against Clerk's JWKS and the user is upserted. With no Clerk
config the app runs in DEV mode as a single seeded user so it works out of the box.
"""
from __future__ import annotations

import logging

import jwt
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import User

log = logging.getLogger("copilot.auth")

DEV_USER_ID = "dev_user"

_jwk_client: jwt.PyJWKClient | None = None


def _jwks() -> jwt.PyJWKClient:
    global _jwk_client
    if _jwk_client is None:
        url = settings.clerk_jwks_url
        if not url and settings.clerk_issuer:
            url = settings.clerk_issuer.rstrip("/") + "/.well-known/jwks.json"
        if not url:
            raise HTTPException(500, "Clerk JWKS URL not configured")
        _jwk_client = jwt.PyJWKClient(url)
    return _jwk_client


def _upsert(db: Session, user_id: str, email: str = "", name: str = "", org_id: str | None = None) -> User:
    user = db.get(User, user_id)
    if user is None:
        user = User(id=user_id, email=email, name=name, org_id=org_id)
        db.add(user)
        db.commit()
    elif email and user.email != email:
        user.email = email
        db.commit()
    return user


def get_current_user(
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> User:
    if settings.dev_mode:
        return _upsert(db, DEV_USER_ID, email="dev@localhost", name="Dev User", org_id="dev_org")

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    token = authorization.split(" ", 1)[1]
    try:
        signing_key = _jwks().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=settings.clerk_issuer,
            options={"verify_aud": False},
        )
    except Exception as exc:  # invalid/expired token
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {exc}") from exc

    return _upsert(
        db,
        user_id=claims["sub"],
        email=claims.get("email", ""),
        name=claims.get("name", ""),
        org_id=claims.get("org_id"),
    )


def user_from_token(db: Session, token: str | None) -> User | None:
    """Resolve a user from a raw token (used for WebSocket query-param auth)."""
    if settings.dev_mode:
        return _upsert(db, DEV_USER_ID, email="dev@localhost", name="Dev User", org_id="dev_org")
    if not token:
        return None
    try:
        signing_key = _jwks().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token, signing_key.key, algorithms=["RS256"], issuer=settings.clerk_issuer,
            options={"verify_aud": False},
        )
        return _upsert(db, claims["sub"], claims.get("email", ""), claims.get("name", ""), claims.get("org_id"))
    except Exception:
        return None
