"""SQLAlchemy ORM models."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


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
    owner_user_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    org_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)  # tenant (for usage/billing)
    pack: Mapped[str] = mapped_column(String(32), default="sales")  # which Copilot Pack drives this meeting
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
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)  # time-to-first (fast path) — the SLA metric
    deep_latency_ms: Mapped[int] = mapped_column(Integer, default=0)  # full agent loop time
    engine: Mapped[str] = mapped_column(String(24), default="offline")
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


class CRMObject(Base):
    """Mock-or-real CRM record. Seeded mock data + auto-created notes/tasks live here."""

    __tablename__ = "crm_objects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    object_type: Mapped[str] = mapped_column(String(24), index=True)  # company|contact|deal|ticket|task|note
    company_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
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

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # Clerk org id or org_<user>
    name: Mapped[str] = mapped_column(String(255), default="Workspace")
    plan: Mapped[str] = mapped_column(String(24), default="free")  # free|pro|enterprise
    seats: Mapped[int] = mapped_column(Integer, default=1)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class User(Base):
    """An employee. `id` is the Clerk user id (or a dev id in DEV mode)."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), default="")
    name: Mapped[str] = mapped_column(String(255), default="")
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), index=True, nullable=True)
    role: Mapped[str] = mapped_column(String(32), default="owner")  # owner|admin|member
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
