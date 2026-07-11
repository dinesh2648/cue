"""Pydantic API schemas (request/response + websocket events)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# ─── Meetings ────────────────────────────────────────────────────────────────
class MeetingCreate(BaseModel):
    # Length caps match the DB columns (String(255)/(32)) so over-long input is rejected
    # with a 422 instead of crashing the insert with StringDataRightTruncation on Postgres.
    title: str = Field("Untitled meeting", max_length=255)
    platform: str = Field("google_meet", max_length=32)
    customer_company: str = Field("", max_length=255)
    customer_contact: str = Field("", max_length=255)
    rep_name: str = Field("", max_length=255)
    crm_company_id: str | None = Field(None, max_length=64)
    pack: str = Field("sales", max_length=32)
    scenario: str | None = None  # name of a seeded simulator scenario


class MeetingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    platform: str
    customer_company: str
    customer_contact: str
    rep_name: str
    status: str
    crm_company_id: str | None
    recall_bot_id: str | None = None
    pack: str
    created_at: datetime
    ended_at: datetime | None


# ─── Transcript / intents / suggestions ──────────────────────────────────────
class SegmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    speaker: str
    role: str
    text: str
    ts: float


class Source(BaseModel):
    label: str
    type: str  # crm|document
    detail: str = ""
    url: str = ""


class SuggestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    intent_type: str
    query_text: str
    answer: str
    evidence: list[str] = Field(default_factory=list)
    sources: list[dict] = Field(default_factory=list)
    actions: list[dict] = Field(default_factory=list)
    confidence: float
    latency_ms: int
    deep_latency_ms: int = 0
    engine: str = "offline"
    grounded: bool = True
    access_scope: str = "demo"
    created_at: datetime


class IntentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    intent_type: str
    query_text: str
    confidence: float


# ─── Summary / CRM ───────────────────────────────────────────────────────────
class SummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    executive_summary: str
    key_decisions: list[str]
    risks: list[str]
    action_items: list[str]
    customer_concerns: list[str]
    follow_up_email: str


class CRMSyncOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    object_type: str
    payload: dict
    external_id: str | None
    status: str
    created_at: datetime


class CRMObjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    object_type: str
    properties: dict
    source: str


class ProposedActionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    meeting_id: str
    pack: str
    action_key: str
    kind: str
    title: str
    payload: dict
    write: bool
    autonomy: str
    status: str
    approver: str | None
    result: dict
    error: str | None
    undoable: bool = False
    created_at: datetime
    decided_at: datetime | None


# ─── Knowledge ───────────────────────────────────────────────────────────────
class KnowledgeHit(BaseModel):
    doc_id: str
    title: str
    doc_type: str
    url: str
    snippet: str
    score: float


# ─── WebSocket events ────────────────────────────────────────────────────────
class WSEvent(BaseModel):
    type: Literal[
        "transcript", "intent", "suggestion", "status", "summary", "crm_sync", "error"
    ]
    data: dict[str, Any]
