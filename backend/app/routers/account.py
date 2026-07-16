"""Account / auth-config endpoints."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import (
    Meeting,
    MeetingScorecard,
    MeetingSummary,
    Organization,
    ProposedAction,
    Suggestion,
    TranscriptSegment,
    User,
)
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
    from .. import capabilities

    return {
        "id": user.id, "email": user.email, "name": user.name,
        "org_id": user.org_id, "role": user.role, "autopilot": user.autopilot,
        "team": user.team, "profile": user.profile or {}, "custom_context": user.custom_context or "",
        "language": user.language or "en",
        "capabilities": capabilities.resolve(user),
        "capability_catalog": capabilities.catalog(),
    }


class CapabilitiesUpdate(BaseModel):
    capabilities: dict[str, bool]  # partial patch — only the keys that changed


@router.post("/me/capabilities")
def set_capabilities(
    body: CapabilitiesUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    """Enable/disable individual copilot capabilities for the signed-in user."""
    from .. import capabilities

    cur = dict(user.capabilities or {})
    for k, v in (body.capabilities or {}).items():
        if k in capabilities.DEFAULTS:
            cur[k] = bool(v)
    user.capabilities = cur
    db.add(user)
    db.commit()
    return {"capabilities": capabilities.resolve(user)}


class ProfileUpdate(BaseModel):
    # Personal advisory context. All optional — send only what changed.
    team: str | None = None            # department: sales|tech|ops|finance|hr|marketing|cs
    language: str | None = None        # ISO code for AI output language (en|ar|fr|…)
    designation: str | None = None
    manager_name: str | None = None
    location: str | None = None
    timezone: str | None = None
    focus: str | None = None
    responsibilities: list[str] | None = None
    decision_authority: list[str] | None = None
    working_style: list[str] | None = None
    preferred_output: list[str] | None = None
    custom_context: str | None = None


@router.post("/me/profile")
def set_profile(
    body: ProfileUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    """Update the signed-in employee's advisory profile — injected into every AI request."""
    from ..advisor.roles import DEPARTMENTS

    if body.team is not None:
        t = body.team.strip().lower()
        user.team = t if t in DEPARTMENTS else user.team
    if body.language is not None:
        from ..advisor.profiles import LANGUAGES
        lang = body.language.strip().lower()
        user.language = lang if lang in LANGUAGES else "en"
    if body.custom_context is not None:
        user.custom_context = body.custom_context[:2000]
    prof = dict(user.profile or {})
    for field in ("designation", "manager_name", "location", "timezone", "focus"):
        v = getattr(body, field)
        if v is not None:
            prof[field] = v.strip()[:200]
    for field in ("responsibilities", "decision_authority", "working_style", "preferred_output"):
        v = getattr(body, field)
        if v is not None:
            prof[field] = [str(x).strip()[:120] for x in v if str(x).strip()][:12]
    user.profile = prof
    db.add(user)
    db.commit()
    return {"team": user.team, "language": user.language, "profile": user.profile, "custom_context": user.custom_context}


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


@router.get("/org/profile")
def get_org_profile(
    organization: Organization = Depends(get_current_org), user: User = Depends(get_current_user)
) -> dict:
    """The company advisory profile — injected into every AI request for all employees."""
    return {
        "name": organization.name,
        "description": organization.description or "",
        "profile": organization.profile or {},
        "can_manage": user.role in ("owner", "admin"),
    }


class CompanyProfileUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    industry: str | None = None
    locations: list[str] | None = None
    products: list[str] | None = None
    tech_stack: list[str] | None = None
    priorities: list[str] | None = None


@router.post("/org/profile")
def set_org_profile(
    body: CompanyProfileUpdate,
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
) -> dict:
    """Update the company profile (owner/admin only)."""
    if user.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Only an owner or admin can edit the company profile.")
    if body.name is not None and body.name.strip():
        organization.name = body.name.strip()[:255]
    if body.description is not None:
        organization.description = body.description[:2000]
    prof = dict(organization.profile or {})
    if body.industry is not None:
        prof["industry"] = body.industry.strip()[:200]
    for field in ("locations", "products", "tech_stack", "priorities"):
        v = getattr(body, field)
        if v is not None:
            prof[field] = [str(x).strip()[:120] for x in v if str(x).strip()][:20]
    organization.profile = prof
    db.add(organization)
    db.commit()
    return {"name": organization.name, "description": organization.description, "profile": organization.profile}


class MemberUpdate(BaseModel):
    role: str | None = None       # member | manager | admin
    team: str | None = None       # department: sales|tech|ops|finance|hr|marketing|cs
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
    if body.role in ("member", "manager", "admin", "owner"):
        # A workspace must always keep at least one owner — block demoting the last one so nobody
        # gets locked out of team management. (Multiple owners are allowed.)
        if member.role == "owner" and body.role != "owner":
            other_owners = db.scalar(
                select(func.count()).select_from(User).where(
                    User.org_id == user.org_id, User.role == "owner", User.id != member.id
                )
            ) or 0
            if other_owners == 0:
                raise HTTPException(400, "Your workspace must keep at least one owner — promote someone else first.")
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


@router.get("/team/members")
def team_members(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Per-member roster (RBAC-scoped): each visible teammate with their meetings and the
    artifacts available on each — transcript, live suggestions, summary, scorecard, recording.
    The frontend links each meeting to its detail page, where those artifacts are shown."""
    vis = visible_user_ids(db, user)
    members = list(db.scalars(select(User).where(User.id.in_(vis))))
    meetings = list(
        db.scalars(select(Meeting).where(Meeting.owner_user_id.in_(vis)).order_by(Meeting.created_at.desc()))
    )
    mids = [m.id for m in meetings]

    def _counts(col):
        if not mids:
            return {}
        return {r[0]: r[1] for r in db.execute(select(col, func.count()).where(col.in_(mids)).group_by(col)).all()}

    seg_counts = _counts(TranscriptSegment.meeting_id)
    sugg_counts = _counts(Suggestion.meeting_id)
    summ_ids = set(db.scalars(select(MeetingSummary.meeting_id).where(MeetingSummary.meeting_id.in_(mids)))) if mids else set()
    scores = (
        {r[0]: r[1] for r in db.execute(
            select(MeetingScorecard.meeting_id, MeetingScorecard.overall_score).where(MeetingScorecard.meeting_id.in_(mids))
        ).all()}
        if mids else {}
    )

    # Actions (approve-then-act writes) per meeting — the team's task/activity trail.
    meeting_by_id = {m.id: m for m in meetings}
    acts_by_meeting: dict[str, list[ProposedAction]] = {}
    if mids:
        for a in db.scalars(
            select(ProposedAction)
            .where(ProposedAction.meeting_id.in_(mids))
            .order_by(ProposedAction.created_at.desc())
        ):
            acts_by_meeting.setdefault(a.meeting_id, []).append(a)

    by_owner: dict[str, list[dict]] = {}
    for m in meetings:
        when = m.ended_at or m.created_at
        macts = acts_by_meeting.get(m.id, [])
        by_owner.setdefault(m.owner_user_id or "", []).append({
            "id": m.id,
            "title": m.title or m.customer_company or "Untitled meeting",
            "customer": m.customer_company,
            "date": when.isoformat() if when else "",
            "status": m.status,
            "actions": len(macts),
            "actions_done": sum(1 for x in macts if x.status in ("executed", "undone")),
            "persona": "tech" if m.pack == "tech" else "sales",
            "suggestions": sugg_counts.get(m.id, 0),
            "has_transcript": seg_counts.get(m.id, 0) > 0,
            "has_summary": m.id in summ_ids,
            "has_recording": bool(m.recall_bot_id),
            "score": scores.get(m.id),
        })

    def _icon(kind: str) -> str:
        return {"note": "📝", "task": "✅", "email": "✉️", "jira_ticket": "🎫", "notion_doc": "📑",
                "reminder": "⏰", "document": "📎", "workflow": "⚙️", "ticket": "🎫", "pr": "🔀"}.get(kind, "•")

    out = []
    for mem in members:
        ms = by_owner.get(mem.id, [])
        scored = [x["score"] for x in ms if x["score"] is not None]
        # This member's task/activity trail — every approve-then-act write across their meetings.
        member_acts = [a for mid in [x["id"] for x in ms] for a in acts_by_meeting.get(mid, [])]
        member_acts.sort(key=lambda a: a.decided_at or a.created_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        activity = {
            "total": len(member_acts),
            "executed": sum(1 for a in member_acts if a.status == "executed"),
            "failed": sum(1 for a in member_acts if a.status == "failed"),
            "undone": sum(1 for a in member_acts if a.status == "undone"),
            "proposed": sum(1 for a in member_acts if a.status == "proposed"),
        }
        recent_actions = [
            {
                "id": a.id,
                "kind": a.kind,
                "icon": _icon(a.kind),
                "title": a.title,
                "status": a.status,
                "url": (a.result or {}).get("url", "") or "",
                "result_status": (a.result or {}).get("status", ""),
                "meeting_id": a.meeting_id,
                "meeting_title": (lambda mm: (mm.title or mm.customer_company or "Meeting") if mm else "Meeting")(meeting_by_id.get(a.meeting_id)),
                "when": (a.decided_at or a.created_at).isoformat() if (a.decided_at or a.created_at) else "",
            }
            for a in member_acts[:15]
        ]
        out.append({
            "id": mem.id,
            "name": mem.name or mem.email or "Unknown",
            "email": mem.email,
            "role": mem.role,
            "team": mem.team,
            "meeting_count": len(ms),
            "avg_score": round(sum(scored) / len(scored)) if scored else None,
            "activity": activity,
            "recent_actions": recent_actions,
            "meetings": ms[:50],
        })
    out.sort(key=lambda x: (-x["meeting_count"], (x["name"] or "").lower()))
    return {"members": out}


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


@router.get("/costs")
def costs(
    days: int = 30,
    user: User = Depends(get_current_user),
    org: Organization = Depends(get_current_org),
    db: Session = Depends(get_db),
) -> dict:
    """Owner/Admin: LLM token + cost accounting for the whole workspace (Phase 0 telemetry).

    Totals plus breakdowns by model, call type, day, user, and top meetings — so an owner can see
    exactly where Anthropic spend goes and prove the effect of cost optimizations later."""
    if user.role not in ("owner", "admin"):
        raise HTTPException(403, "Only an owner or admin can view workspace costs")
    from ..observability.usage import org_cost_summary

    summary = org_cost_summary(db, org.id, days=max(1, min(days, 365)))

    # Enrich ids → friendly labels for the UI.
    uids = [r["user_id"] for r in summary["by_user"] if r["user_id"] and r["user_id"] != "unknown"]
    if uids:
        names = {u.id: (u.name or u.email or u.id) for u in db.scalars(select(User).where(User.id.in_(uids)))}
        for r in summary["by_user"]:
            r["name"] = names.get(r["user_id"], r["user_id"] or "Unattributed")
    else:
        for r in summary["by_user"]:
            r["name"] = r["user_id"] or "Unattributed"

    mids = [r["meeting_id"] for r in summary["top_meetings"] if r["meeting_id"] and r["meeting_id"] != "unknown"]
    if mids:
        titles = {
            m.id: (m.title or m.customer_company or "Untitled meeting")
            for m in db.scalars(select(Meeting).where(Meeting.id.in_(mids)))
        }
        for r in summary["top_meetings"]:
            r["title"] = titles.get(r["meeting_id"], "Meeting")
    else:
        for r in summary["top_meetings"]:
            r["title"] = "Meeting"

    summary["billing_enabled"] = None  # placeholder; costs are computed from token pricing, not Stripe
    return summary
