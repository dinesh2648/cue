"""Build (and cache) a pre-meeting preparation brief for an upcoming calendar event.

Gathers the internal context we already hold — prior meeting notes, CRM snapshot, enterprise
docs — then hands it to the prep agent, which researches the rep's live connected sources
(HubSpot/Notion/Drive/Gmail) + web and writes the brief. Cached per (user, event).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .agent import prep
from .connectors import live_sources
from .connectors.manager import active_mcp_servers, get_access_token
from .integrations import hubspot
from .knowledge.store import index
from .models import Meeting, MeetingPrep, MeetingSummary, User

log = logging.getLogger("copilot.prep_ops")

_CACHE_TTL = timedelta(hours=12)


def _domain(email: str) -> str:
    return email.split("@", 1)[1].lower() if email and "@" in email else ""


def _persona(user: User) -> str:
    return "tech" if (user.team or "").lower() == "tech" else "sales"


# Bump when the prep scaffold/prompt changes so already-cached briefs auto-regenerate with the
# new structure (no migration). The clean _persona above still drives generation; this only
# stamps the cache key. v2 = persona-aware section scaffold (engineering vs sales).
_PREP_VERSION = "8"  # v8: Slack channel history for top match (+ v7 Drive content + Gmail bodies)


def _persona_key(user: User) -> str:
    return f"{_persona(user)}.v{_PREP_VERSION}"


def _customer_guess(external: list[str]) -> str:
    """A human-ish customer label from the most common external attendee domain."""
    if not external:
        return ""
    doms: dict[str, int] = {}
    for a in external:
        d = _domain(a)
        if d:
            doms[d] = doms.get(d, 0) + 1
    if not doms:
        return ""
    top = max(doms, key=doms.get)
    return top.rsplit(".", 1)[0].replace("-", " ").title()  # "acme.com" -> "Acme"


def _gather_history(db: Session, user: User, customer: str, external: set[str], event: dict) -> tuple[list[dict], str | None]:
    """Prior ended meetings in this org tied to the same customer. Returns (history, crm_company_id)."""
    recent = list(
        db.scalars(
            select(Meeting)
            .where(Meeting.org_id == user.org_id, Meeting.status == "ended")
            .order_by(Meeting.created_at.desc())
            .limit(40)
        )
    )
    cust_lc = customer.lower()
    matched: list[Meeting] = []
    for m in recent:
        attendees = {a.lower() for a in (m.attendees or [])}
        if (
            (cust_lc and cust_lc in (m.customer_company or "").lower())
            or (event.get("meeting_url") and m.meeting_url == event["meeting_url"])
            or (m.calendar_event_id and m.calendar_event_id == event.get("id"))
            or (external & attendees)
        ):
            matched.append(m)
        if len(matched) >= 5:
            break

    history: list[dict] = []
    crm_company_id: str | None = None
    for m in matched:
        if m.crm_company_id and not crm_company_id:
            crm_company_id = m.crm_company_id
        ps = db.scalar(select(MeetingSummary).where(MeetingSummary.meeting_id == m.id))
        history.append(
            {
                "date": m.created_at.strftime("%Y-%m-%d") if m.created_at else "",
                "title": m.title,
                "summary": ps.executive_summary if ps else "",
                "decisions": (ps.key_decisions if ps else []) or [],
                "open_actions": (ps.action_items if ps else []) or [],
            }
        )
    return history, crm_company_id


def get_cached(db: Session, user: User, event_id: str) -> MeetingPrep | None:
    return db.scalar(
        select(MeetingPrep)
        .where(MeetingPrep.owner_user_id == user.id, MeetingPrep.calendar_event_id == event_id)
        .order_by(MeetingPrep.generated_at.desc())
    )


def _fresh(row: MeetingPrep | None) -> bool:
    if row is None or row.generated_at is None:
        return False
    gen = row.generated_at if row.generated_at.tzinfo else row.generated_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - gen < _CACHE_TTL


def _usable(row: MeetingPrep | None, user: User) -> bool:
    """A cached prep is usable only if it's fresh AND was generated for the user's current
    persona — so switching team (sales↔tech) invalidates stale briefs automatically."""
    return _fresh(row) and (getattr(row, "persona", "") or "") == _persona_key(user)


async def build_prep(db: Session, user: User, event: dict, *, force: bool = False) -> MeetingPrep:
    """Return a cached fresh prep, or research + generate + cache a new one."""
    event_id = event["id"]
    cached = get_cached(db, user, event_id)
    if cached and _usable(cached, user) and not force:
        return cached

    rep_dom = _domain(user.email or "")
    external = [
        a for a in (event.get("attendees") or [])
        if a and a != user.email and _domain(a) != rep_dom
    ]
    customer = _customer_guess(external) or (event.get("title") or "")
    history, crm_company_id = _gather_history(db, user, customer, {a.lower() for a in external}, event)

    persona = _persona(user)
    crm = hubspot.company_context(db, crm_company_id) if crm_company_id else {}

    # The KnowledgeDoc corpus is sales/CRM-oriented (contracts, pricing, proposals). Pull it only
    # for sales prep, and only when there's an external customer to match against — otherwise it
    # injects irrelevant sales docs into an internal/technical brief (e.g. a dev standup).
    docs = []
    if persona != "tech" and crm_company_id:
        try:
            docs = [
                {"title": h.title, "snippet": h.snippet}
                for h in await index.search(f"{customer} {event.get('title', '')}".strip(), k=4)
            ]
        except Exception:  # pragma: no cover - retrieval best-effort
            docs = []

    servers = await active_mcp_servers(db, user.id)

    # Sources without a hosted MCP (Notion, Drive, Gmail) are read in-process via the user's
    # OAuth token, so EVERY connected source is included — not just the ones with an MCP URL.
    async def _live_token(provider: str) -> str | None:
        tok = await get_access_token(db, user.id, provider)
        return None if (not tok or tok.startswith("demo-")) else tok

    # Notion in-process only for a PAT connection; a DCR connection flows via the remote MCP
    # server in `servers` above (its OAuth token isn't a Notion API PAT).
    from .connectors.manager import get_connection
    _nconn = get_connection(db, user.id, "notion")
    notion_is_dcr = bool(_nconn and (_nconn.oauth_meta or {}).get("token_endpoint"))
    notion_token = None if notion_is_dcr else await _live_token("notion")
    drive_token = await _live_token("google_drive")
    gmail_token = await _live_token("gmail")
    slack_token = await _live_token("slack")  # read in-process via the Slack Web API

    # Pre-fetch recent Gmail / Drive / Slack content for the attendees + topic. Read in-process
    # (no hosted MCP the research path can reach), reading actual email bodies / file text / the top
    # channel's recent thread. Shared verbatim with live answers & the summary (live_sources).
    q = " ".join([customer or event.get("title", ""), *external]).strip()
    comms = await live_sources.gather_comms(
        db, user.id, q,
        tokens={"gmail": gmail_token, "google_drive": drive_token, "slack": slack_token},
        read_bodies=True,
        calendar=False,  # prep is built around THIS event already; skip unrelated upcoming events
    )

    ctx = {
        "title": event.get("title", ""),
        "start": event.get("start", ""),
        "customer": customer,
        "external_attendees": external,
        "organizer": event.get("organizer", ""),
        "crm": crm,
        "history": history,
        "docs": docs,
        "comms": comms,
    }
    result = await prep.generate_prep(
        ctx, persona=_persona(user), servers=servers,
        notion_token=notion_token, drive_token=drive_token, gmail_token=gmail_token,
        slack_token=slack_token,
    )
    # The brief is always built from the calendar event itself (attendees, title, time) — credit it.
    result["sources"] = [
        {"label": "Google Calendar (your account)", "type": "connector", "detail": "this meeting", "url": ""},
        *(result.get("sources") or []),
    ]

    # Replace any prior prep for this (user, event) so the cache holds one row.
    for old in db.scalars(
        select(MeetingPrep).where(
            MeetingPrep.owner_user_id == user.id, MeetingPrep.calendar_event_id == event_id
        )
    ):
        db.delete(old)
    row = MeetingPrep(
        owner_user_id=user.id,
        org_id=user.org_id,
        calendar_event_id=event_id,
        event_title=(event.get("title") or "")[:255],
        event_start=(event.get("start") or "")[:64],
        customer=customer[:255],
        persona=_persona_key(user),
        markdown=result.get("markdown", ""),
        sources=result.get("sources", []),
        engine=result.get("engine", ""),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
