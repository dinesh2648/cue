"""Unit tests for the grounding guardrails (app/advisor/grounding.py).

Pure — no DB, no network. Mirrors scripts/eval_grounding.py so the same rules are covered by
both the CI eval harness and pytest.
"""
from app.advisor import grounding as g


def test_fast_scope_demo_only_in_dev():
    assert g.fast_scope(dev_mode=True, has_evidence=True) == g.DEMO
    assert g.fast_scope(dev_mode=True, has_evidence=False) == g.NONE
    # The core fix: a real (non-dev) user never gets the seeded tier labelled as their data.
    assert g.fast_scope(dev_mode=False, has_evidence=True) == g.NONE
    assert g.fast_scope(dev_mode=False, has_evidence=False) == g.NONE


def test_deep_scope_requires_sources_and_preserves_user_vs_web():
    assert g.deep_scope(has_sources=False, agent_scope="user") == g.NONE
    assert g.deep_scope(has_sources=True, agent_scope="user") == g.USER
    assert g.deep_scope(has_sources=True, agent_scope="web") == g.WEB
    assert g.deep_scope(has_sources=True, agent_scope=None) == g.USER
    assert g.deep_scope(has_sources=True, agent_scope="bogus") == g.USER


def test_verify_downgrades_uncited_grounded_claim():
    ok = g.verify(answer="x", sources=[{"label": "d"}], evidence=[], scope=g.USER)
    assert ok["grounded"] and ok["scope"] == g.USER

    bad = g.verify(answer="x", sources=[], evidence=[], scope=g.USER)
    assert not bad["grounded"] and bad["scope"] == g.NONE

    web = g.verify(answer="x", sources=[], evidence=["e"], scope=g.WEB)
    assert web["grounded"] and web["scope"] == g.WEB

    empty = g.verify(answer="   ", sources=[{"label": "d"}], evidence=[], scope=g.USER)
    assert not empty["ok"]

    none = g.verify(answer="", sources=[], evidence=[], scope=g.NONE)
    assert none["ok"] and not none["grounded"]


def test_abstain_is_honest_and_names_tools():
    a = g.abstain_answer(["HubSpot", "Gmail"])
    assert a["grounded"] is False
    assert a["access_scope"] == g.NONE
    assert not a["sources"] and not a["evidence"]
    assert "HubSpot or Gmail" in a["answer"]
    assert "your tools" in g.abstain_answer([])["answer"]


def test_researching_placeholder_is_not_grounded():
    r = g.researching_answer(["Gmail"])
    assert r["access_scope"] == g.NONE
    assert r["grounded"] is False
    assert "Gmail" in r["answer"]
