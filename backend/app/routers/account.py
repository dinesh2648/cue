"""Account / auth-config endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..config import settings
from ..models import User
from ..security.auth import get_current_user

router = APIRouter(prefix="/api", tags=["account"])


@router.get("/auth/config")
def auth_config() -> dict:
    """Public: lets the frontend decide whether to mount Clerk or run in dev mode."""
    from ..integrations import recall

    return {
        "dev_mode": settings.dev_mode,
        "clerk_publishable_key": settings.clerk_publishable_key,
        "agent_engine": settings.resolved_agent_engine,
        "llm_provider": settings.llm_provider,
        "recall_enabled": recall.enabled(),
    }


@router.get("/me")
def me(user: User = Depends(get_current_user)) -> dict:
    return {"id": user.id, "email": user.email, "name": user.name, "org_id": user.org_id, "role": user.role}


@router.get("/packs")
def packs() -> list[dict]:
    """Copilot Packs live in this deployment. Sales-first rollout exposes only Sales."""
    from ..packs.registry import DEFAULT_PACK, list_packs

    enabled = settings.enabled_pack_list
    return [
        {"key": m.key, "name": m.name, "persona": m.persona, "description": m.description, "default": m.key == DEFAULT_PACK}
        for m in list_packs()
        if m.key in enabled
    ]
