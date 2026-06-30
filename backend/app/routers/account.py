"""Account / auth-config endpoints."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Meeting, MeetingScorecard, Organization, User
from ..security.auth import get_current_org, get_current_user, visible_user_ids

router = APIRouter(prefix="/api", tags=["account"])


@router.get("/auth/config")
def auth_config() -> dict:
    """Public: lets the frontend decide whether to show Google sign-in or run in dev mode."""
    from ..integrations import recall

    return {
        "dev_mode": settings.dev_mode,
        "auth_mode": "google" if settings.google_login_enabled else "dev",
        "google_login_url": (
            f"{settings.app_base_url}/api/auth/google/login" if settings.google_login_enabled else None
        ),
        "agent_engine": settings.resolved_agent_engine,
        "llm_provider": settings.llm_provider,
        "recall_enabled": recall.enabled(),
    }


@router.get("/me")
def me(user: User = Depends(get_current_user)) -> dict:
    return {
        "id": user.id, "email": user.email, "name": user.name,
        "org_id": user.org_id, "role": user.role, "autopilot": user.autopilot,
    }


class AutopilotRequest(BaseModel):
    enabled: bool


@router.post("/me/autopilot")
def set_autopilot(
    body: AutopilotRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    """Toggle auto-pilot — auto-join + auto-summarize the user's external meetings."""
    user.autopilot = body.enabled
    db.add(user)
    db.commit()
    return {"autopilot": user.autopilot}


@router.get("/org")
def org(
    user: User = Depends(get_current_user),
    organization: Organization = Depends(get_current_org),
    db: Session = Depends(get_db),
) -> dict:
    """Current workspace + members (team)."""
    members = db.scalars(select(User).where(User.org_id == organization.id)).all()
    name_by_id = {m.id: (m.name or m.email) for m in members}
    return {
        "id": organization.id,
        "name": organization.name,
        "plan": organization.plan,
        "your_role": user.role,
        "can_manage": user.role in ("owner", "admin"),
        "members": [
            {
                "id": m.id, "email": m.email, "name": m.name, "role": m.role,
                "team": m.team, "manager_id": m.manager_id,
                "manager_name": name_by_id.get(m.manager_id) if m.manager_id else None,
            }
            for m in members
        ],
    }


class MemberUpdate(BaseModel):
    role: str | None = None       # member | manager | admin
    team: str | None = None       # sales | tech | ops
    manager_id: str | None = None  # "" / None clears it


@router.post("/org/members/{member_id}")
def update_member(
    member_id: str,
    body: MemberUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Owner/admin: set a teammate's role, team, and manager."""
    if user.role not in ("owner", "admin"):
        raise HTTPException(403, "Only an owner or admin can manage the team")
    member = db.get(User, member_id)
    if member is None or member.org_id != user.org_id:
        raise HTTPException(404, "Member not found in your workspace")
    if body.role in ("member", "manager", "admin"):
        member.role = body.role
    if body.team in ("sales", "tech", "ops"):
        member.team = body.team
    if body.manager_id is not None:
        mid = body.manager_id or None
        if mid == member.id:
            raise HTTPException(400, "A user can't be their own manager")
        member.manager_id = mid
    db.add(member)
    db.commit()
    return {"id": member.id, "role": member.role, "team": member.team, "manager_id": member.manager_id}


@router.get("/team/coaching")
def team_coaching(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Team coaching rollup — average rep scores across calls the caller may see (RBAC)."""
    vis = visible_user_ids(db, user)
    rows = list(
        db.scalars(
            select(MeetingScorecard)
            .join(Meeting, Meeting.id == MeetingScorecard.meeting_id)
            .where(Meeting.owner_user_id.in_(vis))
        )
    )
    by_rep: dict[str, list[MeetingScorecard]] = {}
    for r in rows:
        by_rep.setdefault(r.rep_name or "Unknown", []).append(r)

    reps = []
    for name, scs in by_rep.items():
        scs_sorted = sorted(scs, key=lambda s: s.created_at or datetime.min.replace(tzinfo=timezone.utc))
        dim_scores: dict[str, list[int]] = {}
        improvements: list[str] = []
        for s in scs:
            for d in s.dimensions or []:
                dim_scores.setdefault(d.get("name", ""), []).append(int(d.get("score") or 0))
            improvements.extend(s.improvements or [])
        recent = [
            {"date": s.created_at.strftime("%b %d") if s.created_at else "", "score": s.overall_score}
            for s in scs_sorted
        ][-12:]
        trend = (recent[-1]["score"] - recent[0]["score"]) if len(recent) > 1 else 0
        reps.append({
            "rep_name": name,
            "calls": len(scs),
            "avg_score": round(sum(s.overall_score for s in scs) / len(scs)),
            "dimensions": [{"name": k, "score": round(sum(v) / len(v))} for k, v in dim_scores.items() if k],
            "top_improvements": list(dict.fromkeys(improvements))[:5],
            "recent": recent,
            "trend": trend,
        })
    reps.sort(key=lambda r: -r["avg_score"])
    return {"reps": reps, "scored_calls": len(rows)}


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
