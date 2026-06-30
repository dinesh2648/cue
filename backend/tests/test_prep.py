"""Tests for the pre-meeting preparation brief (deterministic paths, no network)."""
from __future__ import annotations

import asyncio

from app.agent import prep
from app import prep_ops


def test_customer_guess_from_external_domain():
    assert prep_ops._customer_guess(["olivia@northwind.com", "raj@northwind.com"]) == "Northwind"
    assert prep_ops._customer_guess(["a@acme-corp.io"]) == "Acme Corp"
    assert prep_ops._customer_guess([]) == ""


def test_domain_helper():
    assert prep_ops._domain("a@acme.com") == "acme.com"
    assert prep_ops._domain("noatsign") == ""
    assert prep_ops._domain("") == ""


def test_offline_brief_includes_history_and_attendees():
    ctx = {
        "title": "Acme — renewal",
        "customer": "Acme",
        "external_attendees": ["cto@acme.com"],
        "history": [
            {"date": "2026-06-01", "title": "Discovery", "summary": "Talked pricing.", "open_actions": ["Send SOC2"]}
        ],
        "crm": {"company": {"name": "Acme", "stage": "negotiation"}},
    }
    out = prep._offline_brief(ctx)
    assert out["engine"] == "offline"
    md = out["markdown"]
    assert "Acme" in md
    assert "cto@acme.com" in md
    assert "Send SOC2" in md  # open action surfaced
    assert "Where we left off" in md


def test_offline_brief_empty_context_is_graceful():
    out = prep._offline_brief({"title": "Intro call"})
    assert out["engine"] == "offline"
    assert "Connect HubSpot" in out["markdown"]  # helpful nudge, not a crash


def test_generate_prep_falls_back_to_offline_without_tools_or_llm(monkeypatch):
    # No connected servers/notion AND no LLM available → deterministic offline brief.
    async def _no_llm(*a, **k):
        return None

    monkeypatch.setattr(prep, "llm_complete", _no_llm)
    ctx = {"title": "Sync", "customer": "Beta", "external_attendees": ["x@beta.com"]}
    out = asyncio.run(prep.generate_prep(ctx, persona="sales", servers=[], notion_token=None))
    assert out["engine"] == "offline"
    assert "Beta" in out["markdown"]


def test_compose_prompt_forbids_tool_use():
    # Regression: the no-tools compose path must NOT instruct the model to call tools
    # (that produced hallucinated <function_calls> output).
    assert "NO tools" in prep._SYSTEM_COMPOSE
    assert "do not output function calls" in prep._SYSTEM_COMPOSE.lower()
    # The agent path, by contrast, DOES use tools.
    assert "tools" in prep._SYSTEM_AGENT.lower()
