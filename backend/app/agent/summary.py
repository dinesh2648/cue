"""Post-meeting summary generation (FR-007).

Deterministic heuristics over the transcript + detected intents + CRM snapshot
produce the executive summary, decisions, risks, action items, customer concerns,
and a follow-up email draft. An LLM refines the executive summary + email when
configured; the structured fields stay grounded in what actually happened.
"""
from __future__ import annotations

import json

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


async def generate_summary(
    meeting: dict, intents: list[dict], suggestions: list[dict], crm: dict, transcript: str
) -> dict:
    result = _heuristic(meeting, intents, suggestions, crm)

    raw = await llm_complete(
        system=(
            "You are a sales operations assistant. Given a meeting transcript and a draft summary, "
            "return ONLY a JSON object with keys: executive_summary (string), follow_up_email (string). "
            "Keep the email professional and specific to the transcript. No markdown, JSON only."
        ),
        user=f"Transcript:\n{transcript[:6000]}\n\nDraft summary:\n{json.dumps(result)[:2000]}",
        max_tokens=900,
    )
    if raw:
        try:
            parsed = json.loads(raw[raw.find("{") : raw.rfind("}") + 1])
            if parsed.get("executive_summary"):
                result["executive_summary"] = parsed["executive_summary"]
            if parsed.get("follow_up_email"):
                result["follow_up_email"] = parsed["follow_up_email"]
        except (ValueError, json.JSONDecodeError):
            pass
    return result
