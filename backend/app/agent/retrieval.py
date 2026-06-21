"""Retrieval node (FR-004): pull facts from CRM + enterprise documents.

`crm_context` is precomputed by the caller (HubSpot read) and passed in state, so
this node stays pure. Knowledge retrieval goes through the shared vector/TF-IDF
index. Output: structured `crm_facts` + ranked `knowledge_hits`.
"""
from __future__ import annotations

from ..knowledge.store import index

# Intent-aware query expansion to sharpen document retrieval.
_QUERY_HINTS = {
    "contract_status": "contract MSA agreement signature status terms",
    "implementation_eta": "implementation plan timeline go-live onboarding milestones",
    "open_tickets": "support tickets incidents resolution SLA status",
    "security_review": "SOC2 security compliance encryption data residency whitepaper",
    "proposal_request": "proposal pricing scope statement of work deliverables",
    "pricing": "pricing plans tiers per-seat discount licensing",
    "renewal": "renewal term contract end auto-renew expansion",
    "product_capability": "product features integrations API SSO architecture",
}


def _first_deal(ctx: dict) -> dict:
    deals = ctx.get("deals") or []
    return deals[0] if deals else {}


def extract_crm_facts(intent_type: str, ctx: dict) -> list[dict]:
    """Turn the raw CRM snapshot into intent-relevant fact rows (label, value)."""
    if not ctx:
        return []
    deal = _first_deal(ctx)
    facts: list[dict] = []

    def add(label: str, value, *, source="HubSpot"):
        if value not in (None, "", [], {}):
            facts.append({"label": label, "value": str(value), "source": source})

    if intent_type == "contract_status":
        add("Deal stage", deal.get("dealstage"))
        add("Contract status", deal.get("contract_status"))
        add("Contract value", deal.get("amount") and f"${int(float(deal['amount'])):,}")
        add("Expected close", deal.get("closedate"))
    elif intent_type == "implementation_eta":
        add("Implementation status", deal.get("implementation_status"))
        add("Target go-live", deal.get("go_live_date"))
        add("Onboarding owner", deal.get("onboarding_owner"))
    elif intent_type == "open_tickets":
        add("Open tickets", ctx.get("open_ticket_count"))
        for t in ctx.get("tickets", []):
            if str(t.get("status", "")).lower() != "closed":
                add(f"Ticket #{t.get('id', '')}", f"{t.get('subject')} — {t.get('priority')} / {t.get('status')}")
    elif intent_type == "pricing":
        add("Deal value", deal.get("amount") and f"${int(float(deal['amount'])):,}")
        add("Products", ", ".join(deal.get("line_items", []) or []))
        add("Discount applied", deal.get("discount"))
    elif intent_type == "renewal":
        add("Renewal date", deal.get("renewal_date"))
        add("Current ARR", deal.get("arr") and f"${int(float(deal['arr'])):,}")
        add("Account health", (ctx.get("company") or {}).get("health"))
    elif intent_type == "security_review":
        add("Security questionnaire", deal.get("security_questionnaire_status"))
    elif intent_type == "proposal_request":
        add("Latest proposal", deal.get("latest_proposal"))
        add("Deal value", deal.get("amount") and f"${int(float(deal['amount'])):,}")
    return facts


async def retrieve_node(state: dict) -> dict:
    intent_type = state["intent"]["intent_type"]
    query = state["query_text"]
    hint = _QUERY_HINTS.get(intent_type, "")
    search_query = f"{query} {hint}".strip()

    hits = await index.search(search_query, k=3)

    # Relevance floor (backend-agnostic): drop weak matches so only genuinely
    # relevant documents are cited as sources.
    if hits:
        top = hits[0].score
        floor = max(0.06, 0.4 * top)
        hits = [h for h in hits if h.score >= floor]

    crm_facts = extract_crm_facts(intent_type, state.get("crm_context", {}))

    return {
        "knowledge_hits": [h.__dict__ for h in hits],
        "crm_facts": crm_facts,
    }
