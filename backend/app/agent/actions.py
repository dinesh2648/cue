"""Action-recommendation node (FR-006).

Maps the detected intent to next-best-actions, attaching real seeded documents
where relevant (e.g. security → SOC2 report + whitepaper + NDA workflow). Actions
are structured so the post-meeting automation / UI can execute them.
"""
from __future__ import annotations


def _doc(catalog: list[dict], doc_type: str) -> dict | None:
    for d in catalog:
        if d.get("doc_type") == doc_type:
            return d
    return None


def _share(catalog: list[dict], doc_type: str, fallback_label: str) -> dict:
    d = _doc(catalog, doc_type)
    if d:
        return {
            "label": f"Share {d['title']}",
            "type": "share_document",
            "doc_id": d["id"],
            "url": d.get("url", ""),
        }
    return {"label": fallback_label, "type": "share_document", "doc_id": None, "url": ""}


_ACTIONS_BY_INTENT = {
    "security_review": lambda cat: [
        _share(cat, "soc2", "Share SOC 2 report"),
        _share(cat, "security_whitepaper", "Share security whitepaper"),
        {"label": "Start NDA workflow", "type": "start_workflow", "workflow": "nda"},
        {"label": "Schedule security team review", "type": "schedule_followup", "topic": "Security review"},
    ],
    "contract_status": lambda cat: [
        {"label": "Re-send contract for signature", "type": "start_workflow", "workflow": "docusign"},
        {"label": "Create task: chase countersignature", "type": "create_task", "title": "Chase contract countersignature"},
        _share(cat, "contract", "Share contract summary"),
    ],
    "implementation_eta": lambda cat: [
        _share(cat, "implementation_plan", "Share implementation plan"),
        {"label": "Schedule kickoff call", "type": "schedule_followup", "topic": "Implementation kickoff"},
    ],
    "open_tickets": lambda cat: [
        {"label": "Escalate priority tickets", "type": "escalate", "target": "support"},
        {"label": "Send ticket status summary", "type": "send_email", "topic": "Open ticket status"},
    ],
    "pricing": lambda cat: [
        _share(cat, "pricing", "Share pricing sheet"),
        {"label": "Loop in deal desk", "type": "create_task", "title": "Engage deal desk on pricing options"},
    ],
    "proposal_request": lambda cat: [
        _share(cat, "proposal", "Share latest proposal"),
        {"label": "Schedule proposal walkthrough", "type": "schedule_followup", "topic": "Proposal walkthrough"},
    ],
    "renewal": lambda cat: [
        {"label": "Prepare renewal & expansion options", "type": "create_task", "title": "Prepare renewal options"},
        _share(cat, "proposal", "Share expansion overview"),
    ],
    "product_capability": lambda cat: [
        _share(cat, "product_architecture", "Share product documentation"),
        {"label": "Schedule technical deep-dive", "type": "schedule_followup", "topic": "Technical deep-dive"},
    ],
}


async def actions_node(state: dict) -> dict:
    intent_type = state["intent"]["intent_type"]
    catalog = state.get("doc_catalog", [])
    builder = _ACTIONS_BY_INTENT.get(intent_type)
    actions = builder(catalog) if builder else []
    return {"actions": actions}
