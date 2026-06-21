"""Pydantic API schemas (request/response + websocket events)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# ─── Meetings ────────────────────────────────────────────────────────────────
class MeetingCreate(BaseModel):
    title: str = "Untitled meeting"
    platform: str = "google_meet"
    customer_company: str = ""
    customer_contact: str = ""
    rep_name: str = ""
    crm_company_id: str | None = None
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
