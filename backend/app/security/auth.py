"""Authentication: Google sign-in with our own session JWT, plus a DEV fallback.

When Google OAuth is configured (GOOGLE_CLIENT_ID/SECRET), users sign in with Google.
The backend exchanges the Google code (see routers/auth.py), then issues its *own*
short-lived session JWT (HS256, signed with SESSION_SECRET) which the frontend sends
as `Authorization: Bearer <jwt>`. With no Google config the app runs in DEV mode as a
single seeded user so it works out of the box — no login required.

Tenancy: users are grouped into one workspace by email domain, so all employees at a
company share a tenant. Each still connects their own data, scoped to their own access.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Organization, User

log = logging.getLogger("copilot.auth")

DEV_USER_ID = "dev_user"
_ALG = "HS256"
_SESSION_TTL = timedelta(days=7)

# Personal email providers don't represent a shared company tenant — each such user
# gets their own personal workspace instead of being pooled by domain.
_PERSONAL_DOMAINS = {
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com",
    "yahoo.com", "icloud.com", "me.com", "proton.me", "protonmail.com", "aol.com",
}


def session_key() -> str:
    """Stable 64-char HS256 key derived from the configured secret (always ≥32 bytes).

    Shared by session tokens and the OAuth login state so both sign/verify identically.
    """
    return hashlib.sha256(settings.session_signing_secret.encode()).hexdigest()


def now() -> datetime:
    return datetime.now(timezone.utc)


# ── Session JWTs (issued by us after Google sign-in) ─────────────────────────
def issue_session(user: User) -> str:
    return jwt.encode(
        {
            "sub": user.id,
            "email": user.email,
            "name": user.name,
            "org_id": user.org_id,
            "iat": now(),
            "exp": now() + _SESSION_TTL,
        },
        session_key(),
        algorithm=_ALG,
    )


def verify_session(token: str) -> dict:
    return jwt.decode(token, session_key(), algorithms=[_ALG])


# ── Tenant + user upsert ─────────────────────────────────────────────────────
def _org_for_email(email: str) -> tuple[str, str]:
    """(org_id, display_name) for an email — a shared company tenant, or personal."""
    if "@" in email:
        domain = email.split("@", 1)[1].lower()
        if domain and domain not in _PERSONAL_DOMAINS:
            return f"org_{domain}", domain
        local = email.split("@", 1)[0]
        return f"org_user_{local}", local or "Workspace"
    return "org_workspace", "Workspace"


def _ensure_org(db: Session, org_id: str, name: str) -> Organization:
    org = db.get(Organization, org_id)
    if org is None:
        org = Organization(id=org_id, name=name)
        db.add(org)
        db.commit()
    return org


def upsert_user(db: Session, user_id: str, email: str = "", name: str = "") -> User:
    """Create or update a user, attaching them to their company (email-domain) tenant.

    The first user in a brand-new tenant becomes its owner; later joiners are members.
    """
    oid, oname = _org_for_email(email) if email else (f"org_{user_id}", "Workspace")
    _ensure_org(db, oid, oname)
    user = db.get(User, user_id)
    if user is None:
        existing = db.scalar(select(func.count()).select_from(User).where(User.org_id == oid)) or 0
        user = User(
            id=user_id, email=email, name=name, org_id=oid,
            role="owner" if existing == 0 else "member",
        )
        db.add(user)
        db.commit()
        log.info("new user %s in org %s as %s", user_id, oid, user.role)
    else:
        changed = False
        if email and user.email != email:
            user.email = email
            changed = True
        if name and user.name != name:
            user.name = name
            changed = True
        if not user.org_id:
            user.org_id = oid
            changed = True
        if changed:
            db.commit()
    return user


def _dev_user(db: Session) -> User:
    _ensure_org(db, "dev_org", "Dev Workspace")
    user = db.get(User, DEV_USER_ID)
    if user is None:
        user = User(id=DEV_USER_ID, email="dev@localhost", name="Dev User", org_id="dev_org", role="owner")
        db.add(user)
        db.commit()
    return user


# ── Request dependencies ─────────────────────────────────────────────────────
def get_current_user(
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> User:
    if settings.dev_mode:
        return _dev_user(db)

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    token = authorization.split(" ", 1)[1]
    try:
        claims = verify_session(token)
    except Exception as exc:  # invalid/expired session
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid session: {exc}") from exc
    return upsert_user(db, claims["sub"], claims.get("email", ""), claims.get("name", ""))


def user_from_token(db: Session, token: str | None) -> User | None:
    """Resolve a user from a raw session token (used for WebSocket query-param auth)."""
    if settings.dev_mode:
        return _dev_user(db)
    if not token:
        return None
    try:
        claims = verify_session(token)
        return upsert_user(db, claims["sub"], claims.get("email", ""), claims.get("name", ""))
    except Exception:
        return None


def get_current_org(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Organization:
    """The caller's tenant/workspace."""
    return _ensure_org(db, user.org_id or f"org_{user.id}", "Workspace")


def visible_user_ids(db: Session, user: User) -> set[str]:
    """User ids whose meetings/scorecards this caller may see (RBAC).

    owner/admin → everyone in the org; manager → self + direct reports; member → self.
    """
    if user.role in ("owner", "admin"):
        return {u.id for u in db.scalars(select(User).where(User.org_id == user.org_id))}
    ids = {user.id}
    if user.role == "manager":
        ids |= {u.id for u in db.scalars(select(User).where(User.manager_id == user.id))}
    return ids
