"""SQLAlchemy ORM models."""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _share_token() -> str:
    return secrets.token_urlsafe(24)  # ~32 chars, unguessable — the whole security of a public link


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(255))
    platform: Mapped[str] = mapped_column(String(32), default="google_meet")
    customer_company: Mapped[str] = mapped_column(String(255), default="")
    customer_contact: Mapped[str] = mapped_column(String(255), default="")
    rep_name: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(16), default="scheduled")  # scheduled|live|ended
    crm_company_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recall_bot_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # Recall.ai bot → recording
    meeting_url: Mapped[str | None] = mapped_column(String(512), index=True, nullable=True)  # video-call link (dedup)
    calendar_event_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)  # auto-join dedup
    owner_user_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    org_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)  # tenant (for usage/billing)
    pack: Mapped[str] = mapped_column(String(32), default="sales")  # which Copilot Pack drives this meeting
    attendees: Mapped[list] = mapped_column(JSON, default=list)  # attendee emails — for shared-meeting visibility
    # Evolving meeting state (Meeting Context Manager) — refreshed as the transcript grows so every
    # answer/insight reasons over the WHOLE meeting, not just the latest line.
    # context_json: {current_topic, previous_topics[], open_questions[], decisions[], risks[],
    #   action_items[], entities:{customers[],projects[],tickets[],documents[],opportunities[]}, updated_seg}
    running_summary: Mapped[str] = mapped_column(Text, default="")
    context_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    segments: Mapped[list["TranscriptSegment"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan", order_by="TranscriptSegment.ts"
    )
    intents: Mapped[list["Intent"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )
    suggestions: Mapped[list["Suggestion"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id"), index=True)
    speaker: Mapped[str] = mapped_column(String(120), default="")
    role: Mapped[str] = mapped_column(String(16), default="customer")  # customer|rep|system
    text: Mapped[str] = mapped_column(Text)
    ts: Mapped[float] = mapped_column(Float, default=0.0)  # seconds since meeting start
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    meeting: Mapped[Meeting] = relationship(back_populates="segments")


class Intent(Base):
    __tablename__ = "intents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id"), index=True)
    segment_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    intent_type: Mapped[str] = mapped_column(String(48))
    query_text: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    meeting: Mapped[Meeting] = relationship(back_populates="intents")


class Suggestion(Base):
    __tablename__ = "suggestions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id"), index=True)
    intent_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    intent_type: Mapped[str] = mapped_column(String(48), default="")
    query_text: Mapped[str] = mapped_column(Text, default="")
    answer: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    sources: Mapped[list] = mapped_column(JSON, default=list)
    actions: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    # Advisory envelope: {assumptions[], risks[], next_actions[]} — the structured tail per answer.
    envelope: Mapped[dict] = mapped_column(JSON, default=dict)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)  # time-to-first (fast path) — the SLA metric
    deep_latency_ms: Mapped[int] = mapped_column(Integer, default=0)  # full agent loop time
    engine: Mapped[str] = mapped_column(String(24), default="offline")
    grounded: Mapped[bool] = mapped_column(default=True)  # cited from a real source vs. abstained
    access_scope: Mapped[str] = mapped_column(String(16), default="demo")  # user (live per-user) | demo (seeded)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    meeting: Mapped[Meeting] = relationship(back_populates="suggestions")


class MeetingSummary(Base):
    __tablename__ = "meeting_summaries"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id"), index=True, unique=True)
    executive_summary: Mapped[str] = mapped_column(Text, default="")
    key_decisions: Mapped[list] = mapped_column(JSON, default=list)
    risks: Mapped[list] = mapped_column(JSON, default=list)
    action_items: Mapped[list] = mapped_column(JSON, default=list)
    customer_concerns: Mapped[list] = mapped_column(JSON, default=list)
    follow_up_email: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class MeetingScorecard(Base):
    """Post-call rep coaching scorecard — how the rep handled the call, with scores + tips.

    Stores the overall score + per-dimension breakdown so team-level coaching can aggregate
    across a rep's meetings.
    """

    __tablename__ = "meeting_scorecards"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id"), index=True, unique=True)
    rep_name: Mapped[str] = mapped_column(String(255), default="", index=True)
    overall_score: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    headline: Mapped[str] = mapped_column(Text, default="")
    dimensions: Mapped[list] = mapped_column(JSON, default=list)  # [{name, score, comment}]
    strengths: Mapped[list] = mapped_column(JSON, default=list)
    improvements: Mapped[list] = mapped_column(JSON, default=list)
    coaching_tips: Mapped[list] = mapped_column(JSON, default=list)  # [{tip, example}]
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)  # talk ratio, questions, fillers…
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class MeetingPrep(Base):
    """Pre-meeting preparation brief for an UPCOMING calendar event.

    Agent-researched across the rep's connected sources (HubSpot, Notion, Drive, Gmail) +
    prior meeting notes, cached per (user, calendar event) so it isn't regenerated on every
    page load. Keyed by calendar_event_id because the Meeting row doesn't exist yet.
    """

    __tablename__ = "meeting_preps"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    owner_user_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    org_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)  # tenant scope
    calendar_event_id: Mapped[str] = mapped_column(String(128), index=True)
    event_title: Mapped[str] = mapped_column(String(255), default="")
    event_start: Mapped[str] = mapped_column(String(64), default="")  # ISO string from calendar
    customer: Mapped[str] = mapped_column(String(255), default="")  # inferred customer/company
    persona: Mapped[str] = mapped_column(String(16), default="")  # sales|tech — invalidate on team change
    markdown: Mapped[str] = mapped_column(Text, default="")  # the prep brief (rendered as markdown)
    sources: Mapped[list] = mapped_column(JSON, default=list)  # [{label, type, detail, url}]
    engine: Mapped[str] = mapped_column(String(32), default="")  # claude+mcp | llm | offline
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CRMObject(Base):
    """Mock-or-real CRM record. Seeded mock data + auto-created notes/tasks live here."""

    __tablename__ = "crm_objects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    object_type: Mapped[str] = mapped_column(String(24), index=True)  # company|contact|deal|ticket|task|note
    company_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    org_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)  # tenant scope
    properties: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(16), default="mock")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class KnowledgeDoc(Base):
    """Enterprise document (Google Drive). Indexed by the retriever at startup."""

    __tablename__ = "knowledge_docs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    source: Mapped[str] = mapped_column(String(24), default="google_drive")
    title: Mapped[str] = mapped_column(String(255))
    doc_type: Mapped[str] = mapped_column(String(32), default="")  # security|contract|proposal|...
    mime: Mapped[str] = mapped_column(String(64), default="application/pdf")
    url: Mapped[str] = mapped_column(String(512), default="")
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CRMSyncRecord(Base):
    __tablename__ = "crm_sync_records"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id"), index=True)
    object_type: Mapped[str] = mapped_column(String(24))  # note|task|email_draft
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    external_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="created")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Organization(Base):
    """Tenant / account — the billing + data boundary for a customer."""

    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # org_<email-domain> or org_<user>
    name: Mapped[str] = mapped_column(String(255), default="Workspace")
    plan: Mapped[str] = mapped_column(String(24), default="free")  # free|pro|enterprise
    seats: Mapped[int] = mapped_column(Integer, default=1)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Company advisory context — injected into EVERY AI request so answers fit the business.
    # profile: {industry, locations[], products[], tech_stack[], priorities[]}
    description: Mapped[str] = mapped_column(Text, default="")  # free-text about the company
    profile: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class User(Base):
    """An employee. `id` is `google_<sub>` from Google sign-in (or a dev id in DEV mode)."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), default="")
    name: Mapped[str] = mapped_column(String(255), default="")
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), index=True, nullable=True)
    role: Mapped[str] = mapped_column(String(32), default="owner")  # owner|admin|manager|member
    team: Mapped[str] = mapped_column(String(24), default="sales")  # department: sales|tech|ops|finance|hr|marketing|cs
    manager_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    # Auto-join + auto-summarize my meetings. ON by default (zero-touch) — each user can turn it
    # off at /settings. server_default set in the same migration that backfills existing users.
    autopilot: Mapped[bool] = mapped_column(default=True, server_default=true())
    # Personal advisory context — injected into EVERY AI request so the advisor knows who it's for.
    # profile: {designation, responsibilities[], decision_authority[], working_style[],
    #           preferred_output[], focus, timezone, location, manager_name}
    profile: Mapped[dict] = mapped_column(JSON, default=dict)
    custom_context: Mapped[str] = mapped_column(Text, default="")  # free-text the employee writes about themselves
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ConnectorConnection(Base):
    """A single employee's connection to one provider (per-user OAuth).

    Tokens are stored encrypted (Fernet). Every downstream call runs as this user,
    so the source system enforces what they can see — we never widen access.
    """

    __tablename__ = "connector_connections"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)  # hubspot|google_drive|gmail|notion
    status: Mapped[str] = mapped_column(String(16), default="disconnected")  # connected|disconnected|error
    access_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    account_label: Mapped[str] = mapped_column(String(255), default="")
    mcp_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # DCR/MCP-OAuth context (dynamically-registered client_id/secret + token endpoint) so the
    # token can be refreshed later without re-discovering. Empty for static-OAuth connectors.
    oauth_meta: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class ProposedAction(Base):
    """Approve-then-act: a write the agent proposes; a human approves before it executes.

    Reads/suggestions run freely; every write (CRM note/task, email, shared doc, ticket, PR…)
    lands here as `proposed` until approved, then executes via the user's connector and is audited.
    """

    __tablename__ = "proposed_actions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id"), index=True)
    pack: Mapped[str] = mapped_column(String(32), default="sales")
    action_key: Mapped[str] = mapped_column(String(48))
    kind: Mapped[str] = mapped_column(String(24))  # task|note|email|document|workflow|ticket|pr
    title: Mapped[str] = mapped_column(String(255))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    write: Mapped[bool] = mapped_column(default=True)
    autonomy: Mapped[str] = mapped_column(String(16), default="approve")  # suggest|approve|auto
    status: Mapped[str] = mapped_column(String(16), default="proposed")  # proposed|executed|rejected|failed
    approver: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    """Security requirement: audit logging of all material actions."""

    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    actor: Mapped[str] = mapped_column(String(120), default="system")
    action: Mapped[str] = mapped_column(String(64))
    resource: Mapped[str] = mapped_column(String(120), default="")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ShareLink(Base):
    """A public, read-only link to a meeting's artifacts (prep / transcript / recording / summary).

    Security model: the unguessable `token` IS the access control — anyone with the link sees the
    scoped artifacts, no login. The creator picks which artifacts to expose (`scopes`), can set an
    expiry, and can revoke at any time. Nothing outside the chosen scopes is ever returned.
    """

    __tablename__ = "share_links"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True, default=_share_token)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id"), index=True)
    org_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scopes: Mapped[list] = mapped_column(JSON, default=list)  # any of: prep|transcript|recording|summary
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
