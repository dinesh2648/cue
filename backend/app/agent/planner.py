"""Agentic post-meeting planner — turns a call into typed, executable next actions.

Reads the transcript + summary and produces a plan of typed actions:
  • jira_ticket   — an engineering task/bug/feature to track (tech meetings)
  • notion_doc    — a document/analysis to prepare (e.g. "evaluate Mattermost vs Slack");
                    the agent RESEARCHES + drafts the doc body up front so the human reviews
                    the actual deliverable before approving
  • reminder      — a time-based follow-up
  • task / email  — generic to-do / follow-up

Each becomes a ProposedAction (approve-then-act). On approval the action executes for real
via the owner's connectors (Notion/Calendar/Jira) — see actions/service.py.
"""
from __future__ import annotations

import json
import logging

from .intent import family_for  # noqa: F401 (kept for parity)
from ..integrations.llm import llm_complete

log = logging.getLogger("copilot.planner")

_PLAN_SYSTEM = (
    "You are an agentic chief-of-staff reviewing a meeting. Extract the concrete FOLLOW-UP ACTIONS "
    "that were agreed or clearly implied — what someone now needs to DO. Return ONLY a JSON array; "
    "each item: {\"type\": <one of jira_ticket|notion_doc|reminder|task>, \"title\": <short imperative>, "
    "\"detail\": <1-2 sentences of context/acceptance>}.\n"
    "- jira_ticket: an engineering task, bug or feature to track in Jira (prefer this for technical work).\n"
    "- notion_doc: a document, analysis, comparison, evaluation, spec or RFC to PREPARE "
    "(e.g. 'evaluate Mattermost vs Slack', 'write the integration design'). Use when a deliverable "
    "document is expected.\n"
    "- reminder: a time-based nudge / follow-up to schedule.\n"
    "- task: any other generic to-do.\n"
    "Only include real actions from THIS meeting (max 6). No duplicates. JSON array only, no markdown."
)

_DOC_SYSTEM = (
    "You are a senior analyst writing a clear, decision-ready document for the team. Write the BODY "
    "in clean Markdown (use ## headings, short paragraphs, comparison tables and bullet lists where "
    "useful). Be specific and balanced. If it's a comparison/evaluation, include a criteria table and "
    "a clear recommendation with rationale and concrete next steps. ~400-700 words. No preamble — "
    "start directly with the document."
)


def _as_actions(plan: list, persona: str) -> list[dict]:
    out = []
    for item in plan:
        if not isinstance(item, dict):
            continue
        t = (item.get("type") or "").strip()
        title = (item.get("title") or "").strip()
        detail = (item.get("detail") or "").strip()
        if not title:
            continue
        if t == "jira_ticket":
            out.append({"kind": "jira_ticket", "action_key": "create_jira", "title": title[:255],
                        "payload": {"summary": title, "description": detail}})
        elif t == "notion_doc":
            out.append({"kind": "notion_doc", "action_key": "create_notion_doc", "title": f"Prepare doc: {title}"[:255],
                        "payload": {"title": title, "detail": detail, "body": ""}})
        elif t == "reminder":
            out.append({"kind": "reminder", "action_key": "create_reminder", "title": title[:255],
                        "payload": {"title": title, "detail": detail}})
        else:
            out.append({"kind": "task", "action_key": "create_task", "title": title[:255],
                        "payload": {"title": title, "notes": detail}})
    return out


async def _draft_doc(title: str, detail: str) -> str:
    body = await llm_complete(
        system=_DOC_SYSTEM,
        user=f"Prepare this document: {title}\nContext from the meeting: {detail}",
        max_tokens=2200, temperature=0.4, timeout=60.0,
        call_type="planner_doc",
    )
    return (body or "").strip()


async def plan_actions(*, transcript: str, summary_data: dict, persona: str = "sales") -> list[dict]:
    """Return a list of typed action dicts (kind/action_key/title/payload). Empty on failure."""
    context = (
        f"Decisions: {summary_data.get('key_decisions')}\n"
        f"Action items: {summary_data.get('action_items')}\n"
        f"Concerns: {summary_data.get('customer_concerns')}\n\n"
        f"TRANSCRIPT:\n{transcript[:9000]}"
    )
    raw = await llm_complete(system=_PLAN_SYSTEM, user=context, max_tokens=900, temperature=0.3, timeout=45.0, call_type="planner")
    if not raw:
        return []
    try:
        plan = json.loads(raw[raw.find("[") : raw.rfind("]") + 1])
    except (ValueError, json.JSONDecodeError):
        return []

    actions = _as_actions(plan if isinstance(plan, list) else [], persona)

    # Agentic step: pre-research + draft the body for doc deliverables (cap to 2 for cost).
    drafted = 0
    for a in actions:
        if a["kind"] == "notion_doc" and drafted < 2:
            body = await _draft_doc(a["payload"]["title"], a["payload"].get("detail", ""))
            if body:
                a["payload"]["body"] = body
                drafted += 1
    return actions
