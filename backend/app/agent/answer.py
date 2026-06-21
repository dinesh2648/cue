"""Suggested-answer node (FR-005): Answer · Source · Confidence.

Grounding (CRM facts + retrieved document snippets), source attribution, and
confidence are computed deterministically so they are always trustworthy and
offline-capable. When an LLM is configured it only *polishes the wording* of the
recommended response — it never invents the evidence or the score.
"""
from __future__ import annotations

from ..integrations.llm import llm_complete


def _fact(facts: list[dict], label: str) -> str | None:
    for f in facts:
        if f["label"].lower().startswith(label.lower()):
            return f["value"]
    return None


def _compose_offline(intent_type: str, facts: list[dict], hits: list[dict]) -> str:
    top = hits[0]["snippet"] if hits else ""

    if intent_type == "contract_status":
        status = _fact(facts, "Contract status") or "moving through final review"
        stage = _fact(facts, "Deal stage")
        close = _fact(facts, "Expected close")
        msg = f"Our contract is currently {status.lower()}."
        if stage:
            msg += f" The deal sits in the “{stage}” stage"
            msg += f", and we're targeting close by {close}." if close else "."
        return msg + " Everything on our side is signed — I can re-send the DocuSign link or loop in legal to fast-track the countersignature."

    if intent_type == "implementation_eta":
        status = _fact(facts, "Implementation status")
        go_live = _fact(facts, "Target go-live")
        msg = f"Implementation is {status.lower()}." if status else "We can begin implementation as soon as the contract is signed."
        if go_live:
            msg += f" We're targeting go-live by {go_live}."
        return msg + " Onboarding runs in three phases — provisioning, integration, and UAT — and I can walk your team through the full plan."

    if intent_type == "open_tickets":
        count = _fact(facts, "Open tickets") or "0"
        ticket_lines = [f["value"] for f in facts if f["label"].startswith("Ticket")]
        msg = f"You currently have {count} open support ticket(s)."
        if ticket_lines:
            msg += " The active ones: " + "; ".join(ticket_lines) + "."
        return msg + " I'll personally make sure the high-priority items are escalated today and get you an update by EOD."

    if intent_type == "security_review":
        return (
            "We're SOC 2 Type II certified, and I can share the latest report under NDA along with our "
            "security whitepaper — it covers AES-256 encryption at rest and in transit, configurable data "
            "residency, and full GDPR compliance. I'll send those over right after this call and we can set "
            "up time with our security team for the questionnaire."
        )

    if intent_type == "proposal_request":
        prop = _fact(facts, "Latest proposal")
        val = _fact(facts, "Deal value")
        msg = "I'll share the latest proposal with you right after this call."
        if val:
            msg += f" It reflects the {val} scope we discussed"
            msg += f" and is the version dated {prop}." if prop else "."
        return msg + " Happy to walk through any section live if useful."

    if intent_type == "pricing":
        val = _fact(facts, "Deal value")
        products = _fact(facts, "Products")
        msg = "Pricing is structured around the modules in scope"
        msg += f" ({products})." if products else "."
        if val:
            msg += f" The current proposal lands at {val}."
        return msg + " There's room to align on terms — I can put options in front of our deal desk if you'd like to explore a multi-year arrangement."

    if intent_type == "renewal":
        date = _fact(facts, "Renewal date")
        health = _fact(facts, "Account health")
        msg = f"Your current term renews on {date}." if date else "Let me confirm your exact renewal date and follow up."
        if health:
            msg += f" Account health is currently {health}."
        return msg + " I'd love to use the renewal as a moment to review expansion opportunities — want me to prepare a few options?"

    # product_capability / general — lean on retrieved documentation
    if top:
        return f"Here's what I can confirm from our documentation: {top}"
    return "Let me pull the exact details and get right back to you on that."


def _confidence(intent_conf: float, hits: list[dict], facts: list[dict]) -> float:
    top_score = hits[0]["score"] if hits else 0.0
    retrieval = min(top_score / 0.35, 1.0)  # normalise typical TF-IDF range
    has_crm = 1.0 if facts else 0.0
    conf = 0.45 * intent_conf + 0.30 * retrieval + 0.25 * has_crm
    return round(min(max(conf, 0.05), 0.98), 2)


def _build_sources(company: dict, facts: list[dict], hits: list[dict]) -> list[dict]:
    sources: list[dict] = []
    if facts:
        sources.append(
            {
                "label": "HubSpot CRM",
                "type": "crm",
                "detail": company.get("name", "Customer account") if company else "CRM",
                "url": "",
            }
        )
    for h in hits:
        sources.append(
            {
                "label": h["title"],
                "type": "document",
                "detail": h.get("doc_type", "document"),
                "url": h.get("url", ""),
            }
        )
    return sources


def _build_evidence(facts: list[dict], hits: list[dict]) -> list[str]:
    evidence = [f"{f['label']}: {f['value']}" for f in facts]
    for h in hits[:2]:
        evidence.append(f"{h['title']} — “{h['snippet']}”")
    return evidence


async def answer_node(state: dict) -> dict:
    intent = state["intent"]
    intent_type = intent["intent_type"]
    facts = state.get("crm_facts", [])
    hits = state.get("knowledge_hits", [])
    company = (state.get("crm_context") or {}).get("company", {})

    answer = _compose_offline(intent_type, facts, hits)

    # Optional LLM polish — grounded, never authoritative over evidence/score.
    evidence = _build_evidence(facts, hits)
    if evidence:
        polished = await llm_complete(
            system=(
                "You are a virtual Sales Engineer assisting a rep live on a customer call. "
                "Rewrite the draft answer to be concise (2-3 sentences), warm, and ready to say "
                "out loud. Use ONLY the supplied facts — never invent specifics. Return plain text only."
            ),
            user=(
                f"Customer asked: {state['query_text']}\n\n"
                f"Facts:\n- " + "\n- ".join(evidence) + f"\n\nDraft answer: {answer}"
            ),
            max_tokens=220,
        )
        if polished:
            answer = polished

    return {
        "answer": answer,
        "evidence": evidence,
        "sources": _build_sources(company, facts, hits),
        "confidence": _confidence(intent["confidence"], hits, facts),
    }
