"""Grounding eval harness — exercises the grounding guardrails against labelled scenarios.

This is the regression net for the product's core promise ("answers are grounded, or we say
so"). It is pure: it loads app/advisor/grounding.py directly, so it runs with zero deps —

    python scripts/eval_grounding.py        # from backend/

Prints a pass/fail table and exits non-zero if any case fails. Wire it into CI so a change
that lets ungrounded / seeded answers masquerade as the user's real data fails the build.
"""
from __future__ import annotations

import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_GPATH = os.path.join(_HERE, "..", "app", "advisor", "grounding.py")
_spec = importlib.util.spec_from_file_location("grounding", _GPATH)
g = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(g)


def cases() -> list[tuple[str, object, object]]:
    """Each case: (name, actual, expected)."""
    docs = [{"label": "doc"}]
    return [
        # ── fast_scope: seeded tier is DEMO only in dev mode; never a real user's data ──
        ("fast: dev + evidence → demo", g.fast_scope(dev_mode=True, has_evidence=True), g.DEMO),
        ("fast: dev + no evidence → none", g.fast_scope(dev_mode=True, has_evidence=False), g.NONE),
        ("fast: prod + evidence → none (no demo leak)", g.fast_scope(dev_mode=False, has_evidence=True), g.NONE),
        ("fast: prod + no evidence → none", g.fast_scope(dev_mode=False, has_evidence=False), g.NONE),

        # ── deep_scope: LIVE only with real sources; preserve user-vs-web ──
        ("deep: no sources → none", g.deep_scope(has_sources=False, agent_scope="user"), g.NONE),
        ("deep: sources + user → user", g.deep_scope(has_sources=True, agent_scope="user"), g.USER),
        ("deep: sources + web → web", g.deep_scope(has_sources=True, agent_scope="web"), g.WEB),
        ("deep: sources + unknown → user", g.deep_scope(has_sources=True, agent_scope=None), g.USER),
        ("deep: sources + 'demo' → user", g.deep_scope(has_sources=True, agent_scope="demo"), g.USER),

        # ── verify: a grounded scope must actually cite; else downgrade to NONE ──
        ("verify: user + sources → grounded user",
         g.verify(answer="a", sources=docs, evidence=[], scope=g.USER)["scope"], g.USER),
        ("verify: user + no cite → downgraded none",
         g.verify(answer="a", sources=[], evidence=[], scope=g.USER)["scope"], g.NONE),
        ("verify: user + no cite → grounded False",
         g.verify(answer="a", sources=[], evidence=[], scope=g.USER)["grounded"], False),
        ("verify: web + evidence → grounded web",
         g.verify(answer="a", sources=[], evidence=["e"], scope=g.WEB)["scope"], g.WEB),
        ("verify: demo + cite → grounded",
         g.verify(answer="a", sources=docs, evidence=[], scope=g.DEMO)["grounded"], True),
        ("verify: none → not grounded",
         g.verify(answer="", sources=[], evidence=[], scope=g.NONE)["grounded"], False),
        ("verify: empty answer + cite → not ok",
         g.verify(answer="  ", sources=docs, evidence=[], scope=g.USER)["ok"], False),

        # ── abstain: honest, never grounded, scope NONE, names the missing tools ──
        ("abstain: grounded False", g.abstain_answer(["Gmail"])["grounded"], False),
        ("abstain: scope none", g.abstain_answer(["Gmail"])["access_scope"], g.NONE),
        ("abstain: names one tool", "Gmail" in g.abstain_answer(["Gmail"])["answer"], True),
        ("abstain: joins two tools", "HubSpot or Gmail" in g.abstain_answer(["HubSpot", "Gmail"])["answer"], True),
        ("abstain: no tools → generic", "your tools" in g.abstain_answer([])["answer"], True),

        # ── researching placeholder: honest, not grounded, scope none ──
        ("researching: scope none", g.researching_answer(["Gmail"])["access_scope"], g.NONE),
        ("researching: grounded False", g.researching_answer(["Gmail"])["grounded"], False),
        ("researching: mentions the source", "Gmail" in g.researching_answer(["Gmail"])["answer"], True),
    ]


def main() -> int:
    rows = cases()
    failed = 0
    for name, actual, expected in rows:
        ok = actual == expected
        if not ok:
            failed += 1
        mark = "PASS" if ok else "FAIL"
        detail = "" if ok else f"   (got {actual!r}, expected {expected!r})"
        print(f"  [{mark}] {name}{detail}")
    total = len(rows)
    print(f"\n{total - failed}/{total} grounding cases passed"
          + ("" if not failed else f" — {failed} FAILED"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
