"""Offline tests for intent detection, the agent pipeline, and summarization."""
from __future__ import annotations

import asyncio

from app.agent.intent import detect_intent
from app.agent.pipeline import pipeline
from app.agent.summary import generate_summary
from app.knowledge.store import index

CRM_CONTEXT = {
    "company": {"name": "Northwind Trading", "health": "Yellow"},
    "deals": [
        {
            "dealname": "Expansion",
            "dealstage": "Contract Sent",
            "amount": "120000",
            "closedate": "2026-07-15",
            "contract_status": "Sent for signature — awaiting countersignature",
            "go_live_date": "2026-08-01",
            "implementation_status": "Ready to begin on signature",
            "security_questionnaire_status": "In progress — 80%",
        }
    ],
    "tickets": [
        {"id": "T-1", "subject": "SSO issue", "priority": "High", "status": "Open"},
        {"id": "T-2", "subject": "Export slow", "priority": "Medium", "status": "In Progress"},
    ],
    "open_ticket_count": 2,
}

DOCS = [
    {"id": "d1", "title": "SOC 2 Report", "doc_type": "soc2", "url": "u", "content": "Atlas Cloud is SOC 2 Type II certified with AES-256 encryption and GDPR compliance."},
    {"id": "d2", "title": "Implementation Plan", "doc_type": "implementation_plan", "url": "u", "content": "Implementation runs four weeks across provisioning, integration, and UAT phases before go-live."},
    {"id": "d3", "title": "Pricing", "doc_type": "pricing", "url": "u", "content": "Per-seat pricing with volume and multi-year discounts up to 18 percent."},
]


def _build_index():
    asyncio.get_event_loop().run_until_complete(index.build(DOCS))


def test_intent_detection():
    assert detect_intent("What is the status of our contract?").intent_type == "contract_status"
    assert detect_intent("Can you share your SOC 2 report?").intent_type == "security_review"
    assert detect_intent("How many support tickets are open?").intent_type == "open_tickets"
    assert detect_intent("What's the ETA for implementation?").intent_type == "implementation_eta"
    assert detect_intent("Just saying hi").actionable is False


def test_pipeline_produces_grounded_suggestion():
    asyncio.run(index.build(DOCS))

    async def run():
        catalog = [{"id": d["id"], "title": d["title"], "doc_type": d["doc_type"], "url": d["url"]} for d in DOCS]
        state = {
            "query_text": "Can you share your SOC 2 report and confirm encryption?",
            "crm_context": CRM_CONTEXT,
            "doc_catalog": catalog,
        }
        result = await pipeline.ainvoke(state)
        return result

    result = asyncio.run(run())
    assert result["intent"]["intent_type"] == "security_review"
    assert result["answer"]
    assert 0.0 < result["confidence"] <= 0.98
    assert any(a["type"] == "share_document" for a in result["actions"])


def test_summary_generation():
    async def run():
        return await generate_summary(
            meeting={"customer_company": "Northwind Trading", "customer_contact": "Sarah Chen", "rep_name": "Alex Rivera"},
            intents=[{"intent_type": "contract_status"}, {"intent_type": "security_review"}, {"intent_type": "open_tickets"}],
            suggestions=[{"actions": [{"label": "Share SOC 2 report"}]}],
            crm=CRM_CONTEXT,
            transcript="Sarah: what's our contract status? Alex: let me check.",
        )

    summary = asyncio.run(run())
    assert summary["executive_summary"]
    assert summary["action_items"]
    assert "Sarah" in summary["follow_up_email"]
    assert summary["risks"]
