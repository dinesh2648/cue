"""Assembles the copilot agent graph.

    START → intent → (actionable?) → retrieve → answer → actions → END
                          └────────── no ──────────────────────► END

Lifts directly onto `langgraph` (same StateGraph API).
"""
from __future__ import annotations

from .actions import actions_node
from .answer import answer_node
from .graph import END, StateGraph
from .intent import detect_intent
from .retrieval import retrieve_node


async def intent_node(state: dict) -> dict:
    res = detect_intent(state["query_text"])
    return {
        "intent": {
            "intent_type": res.intent_type,
            "family": res.family,
            "confidence": res.confidence,
            "query_text": res.query_text,
        },
        "_actionable": res.actionable,
    }


def _route(state: dict) -> str:
    return "go" if state.get("_actionable") else "skip"


def build_pipeline():
    g = StateGraph()
    g.add_node("intent", intent_node)
    g.add_node("retrieve", retrieve_node)
    g.add_node("answer", answer_node)
    g.add_node("actions", actions_node)
    g.set_entry_point("intent")
    g.add_conditional_edges("intent", _route, {"go": "retrieve", "skip": END})
    g.add_edge("retrieve", "answer")
    g.add_edge("answer", "actions")
    g.add_edge("actions", END)
    return g.compile()


pipeline = build_pipeline()
