"""Post-meeting summary generation (FR-007).

Deterministic heuristics over the transcript + detected intents + CRM snapshot
produce the executive summary, decisions, risks, action items, customer concerns,
and a follow-up email draft. An LLM refines the executive summary + email when
configured; the structured fields stay grounded in what actually happened.
"""
from __future__ import annotations

import json

from ..connectors.live_sources import format_comms
from ..integrations.llm import llm_complete

_CONCERNS = {
    "contract_status": "Status and timing of the contract / countersignature",
    "implementation_eta": "Implementation timeline and go-live date",
    "open_tickets": "Open support tickets and their resolution",
    "security_review": "Security posture, SOC 2, and compliance review",
    "proposal_request": "Reviewing the latest proposal",
    "pricing": "Pricing and commercial terms",
    "renewal": "Upcoming renewal and expansion",
    "product_capability": "Product capabilities and fit",
}

_DECISIONS = {
    "contract_status": "Customer to countersign the MSA so onboarding can begin",
    "security_review": "We will provide the SOC 2 report under NDA plus the security whitepaper",
    "implementation_eta": "Align on a target go-live date and schedule kickoff",
    "proposal_request": "Share the latest proposal for review",
    "pricing": "Explore commercial options with the deal desk",
    "renewal": "Prepare renewal and expansion options ahead of the term end",
}


def _first_name(full: str) -> str:
    return (full or "there").split()[0] if full else "there"


def _heuristic(meeting: dict, intents: list[dict], suggestions: list[dict], crm: dict) -> dict:
    intent_types: list[str] = []
    for i in intents:
        if i["intent_type"] not in intent_types and i["intent_type"] != "general":
            intent_types.append(i["intent_type"])

    concerns = [_CONCERNS[t] for t in intent_types if t in _CONCERNS]
    decisions = [_DECISIONS[t] for t in intent_types if t in _DECISIONS]

    # Action items — unique action labels surfaced during the call.
    seen: set[str] = set()
    action_items: list[str] = []
    for s in suggestions:
        for a in s.get("actions", []):
            label = a.get("label")
            if label and label not in seen:
                seen.add(label)
                action_items.append(label)
    action_items.append("Send recap email to the customer")

    # Risks from the live CRM snapshot.
    risks: list[str] = []
    deal = (crm.get("deals") or [{}])[0]
    if crm.get("open_ticket_count"):
        risks.append(
            f"{crm['open_ticket_count']} open support ticket(s) may weigh on customer confidence"
        )
    if deal.get("contract_status") and "sign" in deal["contract_status"].lower():
        risks.append("Contract awaiting countersignature — close date at risk until executed")
    if deal.get("security_questionnaire_status") and "complete" not in str(
        deal["security_questionnaire_status"]
    ).lower():
        risks.append("Security questionnaire still outstanding")
    if not risks:
        risks.append("No major risks surfaced; maintain momentum on next steps")

    company = meeting.get("customer_company", "the customer")
    topics = ", ".join(concerns[:-1]) + (f", and {concerns[-1]}" if len(concerns) > 1 else "")
    topics = topics or (concerns[0] if concerns else "general account questions")
    exec_summary = (
        f"Call with {company}"
        + (f" ({meeting.get('customer_contact')})" if meeting.get("customer_contact") else "")
        + f". The customer raised {len(intent_types)} key topic(s): {topics}. "
        + "The copilot surfaced grounded answers from CRM and enterprise docs in real time, and "
        + f"{len(action_items)} follow-up action(s) were captured for the rep."
    )

    email = _email(meeting, concerns, action_items)
    return {
        "executive_summary": exec_summary,
        "key_decisions": decisions or ["Continue evaluation; no firm decisions yet"],
        "risks": risks,
        "action_items": action_items,
        "customer_concerns": concerns or ["General account discussion"],
        "follow_up_email": email,
    }


def _email(meeting: dict, concerns: list[str], actions: list[str]) -> str:
    name = _first_name(meeting.get("customer_contact", ""))
    rep = meeting.get("rep_name") or "Your Account Team"
    recap = "\n".join(f"  • {c}" for c in concerns) or "  • Our discussion today"
    steps = "\n".join(f"  • {a}" for a in actions if "email" not in a.lower()) or "  • We'll follow up shortly"
    return (
        f"Subject: Recap & next steps — {meeting.get('customer_company', 'our conversation')}\n\n"
        f"Hi {name},\n\n"
        "Thanks for the time today — great conversation. Here's a quick recap of what we covered:\n\n"
        f"{recap}\n\n"
        "Next steps on our side:\n\n"
        f"{steps}\n\n"
        "I'll get the items above moving right away. Please let me know if I missed anything, "
        "and I'm happy to set up time with the right people on our team.\n\n"
        f"Best regards,\n{rep}"
    )


_SUMMARY_SYSTEM = (
    "You are a senior sales operations assistant writing the post-meeting brief. You are given the "
    "CURRENT meeting transcript, summaries of PREVIOUS meetings with this SAME client, the CRM "
    "snapshot, and relevant enterprise documents. Synthesize ALL of it — connect this call to the "
    "history (what progressed, stalled, or changed since last time).\n"
    "Return ONLY a JSON object with these keys:\n"
    "- executive_summary: 3-5 sentences. What happened this call and how it moves the relationship "
    "vs. prior conversations. Specific and grounded.\n"
    "- customer_concerns: array of the customer's actual concerns/questions raised this call.\n"
    "- key_decisions: array of concrete decisions or agreements reached.\n"
    "- risks: array of risks to the deal (open tickets, unsigned contract, unresolved items, stalls).\n"
    "- action_items: array of specific next steps for the rep (your side), each ONE concise "
    "sentence (max ~140 chars).\n"
    "- follow_up_email: a professional recap email to the customer referencing the ACTUAL discussion "
    "and concrete next steps. Start with a 'Subject:' line. Plain text, no markdown.\n"
    "Ground every point strictly in the material provided — never invent facts, names, or numbers. "
    "When previous meetings are provided, explicitly build on them. Output JSON only."
)

# Tech persona: engineering/delivery framing (decisions, tickets, blockers) — not sales.
_SUMMARY_SYSTEM_TECH = (
    "You are a senior engineering/delivery lead writing the post-meeting brief for a technical "
    "team. You are given the CURRENT meeting transcript, summaries of PREVIOUS related meetings, "
    "any CRM/project snapshot, and relevant docs. Synthesize ALL of it — connect this discussion "
    "to what progressed, got unblocked, or changed since last time.\n"
    "Return ONLY a JSON object with these keys:\n"
    "- executive_summary: 3-5 sentences. What was discussed/decided technically and how it moves "
    "the work forward. Specific and grounded.\n"
    "- customer_concerns: array of open questions / concerns raised (technical or from stakeholders).\n"
    "- key_decisions: array of concrete technical decisions or agreements (design choices, "
    "approach, ownership, scope).\n"
    "- risks: array of delivery risks — blockers, dependencies, tech debt, unresolved bugs, "
    "unclear requirements, timeline threats.\n"
    "- action_items: array of specific next steps for the team, each ONE concise sentence "
    "(max ~140 chars) — phrased as engineering tasks (e.g. 'Open a Jira ticket to…', 'Spike…', "
    "'Raise a PR for…').\n"
    "- follow_up_email: a concise recap message to the team/stakeholders with decisions and next "
    "steps. Start with a 'Subject:' line. Plain text, no markdown.\n"
    "Ground every point strictly in the material provided — never invent facts. Output JSON only."
)


def _crm_brief(crm: dict) -> str:
    deal = (crm.get("deals") or [{}])[0]
    lines = []
    for k in ("dealstage", "contract_status", "amount", "closedate", "go_live_date",
              "renewal_date", "security_questionnaire_status"):
        if deal.get(k):
            lines.append(f"  {k}: {deal[k]}")
    if crm.get("open_ticket_count") is not None:
        lines.append(f"  open_tickets: {crm.get('open_ticket_count')}")
    for t in (crm.get("tickets") or [])[:5]:
        lines.append(f"  ticket {t.get('id')}: {t.get('subject')} [{t.get('status')}/{t.get('priority')}]")
    return "\n".join(lines) or "  (no CRM data on file)"


def _history_brief(history: list[dict]) -> str:
    if not history:
        return "  None on record — this appears to be the first meeting with this client."
    out = []
    for h in history:
        line = f"  • [{h.get('date', '')}] {h.get('title', 'Meeting')}: {h.get('summary', '') or '(no summary)'}"
        if h.get("decisions"):
            line += "\n      decisions: " + "; ".join(h["decisions"][:4])
        if h.get("open_actions"):
            line += "\n      action items: " + "; ".join(h["open_actions"][:4])
        out.append(line)
    return "\n".join(out)


def _build_context(meeting, intents, suggestions, crm, transcript, history, docs, comms) -> str:
    topics = sorted({i["intent_type"] for i in intents if i.get("intent_type") and i["intent_type"] != "general"})
    answers = [s.get("answer", "") for s in suggestions if s.get("answer")]
    docs_block = "\n".join(f"  • {d.get('title')}: {(d.get('snippet') or '')[:160]}" for d in docs) or "  (none)"
    comms_block = format_comms(comms or [], max_chars=4000)
    return (
        f"CLIENT: {meeting.get('customer_company', 'Unknown')}"
        f" | Contact: {meeting.get('customer_contact', '—')}"
        f" | Rep: {meeting.get('rep_name', '—')}\n\n"
        f"PREVIOUS MEETINGS WITH THIS CLIENT (most recent first):\n{_history_brief(history)}\n\n"
        f"CRM SNAPSHOT:\n{_crm_brief(crm)}\n\n"
        f"RELEVANT ENTERPRISE DOCUMENTS:\n{docs_block}\n\n"
        f"RECENT EMAIL / DRIVE / SLACK ON THIS ACCOUNT (the owner's own connected sources):\n"
        f"{comms_block or '  (none)'}\n\n"
        f"THIS MEETING — topics the customer raised: {', '.join(topics) or 'general discussion'}\n"
        f"THIS MEETING — answers the copilot gave:\n"
        + ("\n".join(f"  • {a[:200]}" for a in answers[:8]) or "  (none)")
        + f"\n\nCURRENT MEETING TRANSCRIPT:\n{transcript[:9000]}"
    )


def _as_list(v) -> list[str] | None:
    if isinstance(v, list):
        items = [str(x).strip() for x in v if str(x).strip()]
        return items or None
    return None


async def generate_summary(
    meeting: dict,
    intents: list[dict],
    suggestions: list[dict],
    crm: dict,
    transcript: str,
    history: list[dict] | None = None,
    docs: list[dict] | None = None,
    persona: str = "sales",
    comms: list[dict] | None = None,
) -> dict:
    """Synthesize the post-meeting brief from the current transcript, prior meetings with the
    same client, the CRM snapshot, enterprise docs, and the owner's live Gmail/Drive/Slack
    content (`comms`). Heuristic baseline is the fallback.
    `persona` ('tech'|'sales') sets whether the brief is engineering- or sales-framed."""
    base = _heuristic(meeting, intents, suggestions, crm)

    raw = await llm_complete(
        system=_SUMMARY_SYSTEM_TECH if persona == "tech" else _SUMMARY_SYSTEM,
        user=_build_context(meeting, intents, suggestions, crm, transcript, history or [], docs or [], comms or []),
        max_tokens=1800,
        temperature=0.3,
        timeout=60.0,  # large structured generation — well above the default 20s
    )
    if not raw:
        return base
    try:
        parsed = json.loads(raw[raw.find("{") : raw.rfind("}") + 1])
    except (ValueError, json.JSONDecodeError):
        return base

    return {
        "executive_summary": (parsed.get("executive_summary") or "").strip() or base["executive_summary"],
        "key_decisions": _as_list(parsed.get("key_decisions")) or base["key_decisions"],
        "risks": _as_list(parsed.get("risks")) or base["risks"],
        "action_items": _as_list(parsed.get("action_items")) or base["action_items"],
        "customer_concerns": _as_list(parsed.get("customer_concerns")) or base["customer_concerns"],
        "follow_up_email": (parsed.get("follow_up_email") or "").strip() or base["follow_up_email"],
    }
