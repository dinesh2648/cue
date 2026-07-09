"""User + Company advisory context — assembled once and injected into EVERY AI request.

The Core Principle: the advisor never answers in isolation. These blocks put the employee (who
they are, their role, decision authority, how they like answers) and the company (what it does,
its stack and priorities) into the prompt every single time — for prep, live answers, Ask and the
post-meeting write-up alike. Only fields that are filled are rendered, so a sparse profile stays
compact and an empty one adds nothing.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import Organization, User
from .roles import department_label, role_directive


def _lines(label: str, value) -> list[str]:
    """Render 'label: a, b, c' for a list, 'label: value' for a scalar — or nothing if empty."""
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        items = [str(v).strip() for v in value if str(v).strip()]
        return [f"{label}: {', '.join(items)}"] if items else []
    v = str(value).strip()
    return [f"{label}: {v}"] if v else []


def user_context_block(user: User | None) -> str:
    if user is None:
        return ""
    p = getattr(user, "profile", None) or {}
    out: list[str] = []
    name = (user.name or user.email or "").strip()
    header = name or "this employee"
    desig = str(p.get("designation") or "").strip()
    out.append(f"Advising: {header}" + (f" — {desig}" if desig else "") + f" ({department_label(user)}).")
    out += _lines("Reports to", p.get("manager_name"))
    out += _lines("Location", p.get("location"))
    out += _lines("Timezone", p.get("timezone"))
    out += _lines("Responsibilities", p.get("responsibilities"))
    out += _lines("Decision authority", p.get("decision_authority"))
    out += _lines("Working style", p.get("working_style"))
    out += _lines("Preferred output", p.get("preferred_output"))
    out += _lines("Focus", p.get("focus"))
    custom = (getattr(user, "custom_context", "") or "").strip()
    if custom:
        out.append(f"In their own words: {custom[:800]}")
    return "\n".join(out)


def company_context_block(org: Organization | None) -> str:
    if org is None:
        return ""
    p = getattr(org, "profile", None) or {}
    out: list[str] = []
    name = (org.name or "").strip()
    if name and name.lower() != "workspace":
        out.append(f"Company: {name}")
    out += _lines("Industry", p.get("industry"))
    out += _lines("Locations", p.get("locations"))
    out += _lines("Products", p.get("products"))
    out += _lines("Tech stack", p.get("tech_stack"))
    out += _lines("Business priorities", p.get("priorities"))
    desc = (getattr(org, "description", "") or "").strip()
    if desc:
        out.append(f"About: {desc[:800]}")
    return "\n".join(out)


def advisory_preamble(user: User | None, org: Organization | None) -> str:
    """The always-on context block. Empty string when nothing is configured (no noise)."""
    uc = user_context_block(user)
    cc = company_context_block(org)
    if not uc and not cc:
        return ""
    parts = ["## Who you are advising"]
    if uc:
        parts.append(uc)
    if cc:
        parts.append("\n## Company context\n" + cc)
    parts.append("\n" + role_directive(user))
    parts.append(
        "Tailor the answer to this person's role, decision authority and preferred output. "
        "Ground everything in the sources provided; never invent facts about the person or company."
    )
    return "\n".join(parts)


def load_preamble(db: Session, user_id: str | None) -> str:
    """Load the employee + their org and build the always-on advisory preamble. Flows call this
    with just (db, user_id); returns '' when the user/org can't be resolved."""
    if not user_id:
        return ""
    user = db.get(User, user_id)
    if user is None:
        return ""
    org = db.get(Organization, user.org_id) if user.org_id else None
    return advisory_preamble(user, org)
