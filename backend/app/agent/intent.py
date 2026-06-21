"""Real-time intent detection (FR-003).

Deterministic, fast (<5ms), offline keyword/pattern scorer that maps a customer
utterance to one of the PRD intent families. This is the latency-critical path,
so it is rule-based by design; an LLM classifier can be layered on top when keys
are present without changing the interface.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# intent_type -> (PRD family, weighted keyword groups)
_INTENT_KEYWORDS: dict[str, tuple[str, list[tuple[float, list[str]]]]] = {
    "contract_status": (
        "contract",
        [
            (2.0, ["contract", "msa", "agreement", "docusign", "countersign", "redline"]),
            (1.0, ["sign", "signed", "signature", "paperwork", "terms", "legal", "executed"]),
        ],
    ),
    "implementation_eta": (
        "product",
        [
            (2.0, ["eta", "timeline", "go live", "go-live", "implementation", "rollout"]),
            (1.0, ["deploy", "onboarding", "kickoff", "how long", "when can we", "live by", "launch"]),
        ],
    ),
    "open_tickets": (
        "support",
        [
            (2.0, ["ticket", "tickets", "open issues", "support request"]),
            (1.0, ["bug", "incident", "outage", "escalation", "broken", "not working"]),
        ],
    ),
    "security_review": (
        "security",
        [
            (2.0, ["soc2", "soc 2", "security questionnaire", "pentest", "penetration"]),
            (1.0, ["security", "compliance", "gdpr", "iso", "encryption", "data residency", "vulnerability", "whitepaper", "audit"]),
        ],
    ),
    "proposal_request": (
        "product",
        [
            (2.0, ["proposal", "sow", "statement of work", "latest deck"]),
            (1.0, ["quote", "send over", "share the latest", "presentation", "one pager", "one-pager"]),
        ],
    ),
    "pricing": (
        "pricing",
        [
            (2.0, ["pricing", "price", "discount", "how much", "cost"]),
            (1.0, ["budget", "license", "per seat", "seats", "tier", "quote", "list price"]),
        ],
    ),
    "renewal": (
        "renewal",
        [
            (2.0, ["renew", "renewal", "auto-renew", "auto renew"]),
            (1.0, ["expire", "expiration", "term end", "end of term", "extend"]),
        ],
    ),
    "product_capability": (
        "product",
        [
            (2.0, ["does it", "can it", "do you support", "is there a way", "roadmap"]),
            (1.0, ["feature", "integrate", "integration", "api", "sso", "scale", "capability", "limit"]),
        ],
    ),
}

_QUESTION_RE = re.compile(
    r"\?|\b(what|when|how|can|do|does|is|are|could|would|will|where|which|who|any)\b",
    re.IGNORECASE,
)


@dataclass
class IntentResult:
    intent_type: str
    family: str
    confidence: float
    query_text: str

    @property
    def actionable(self) -> bool:
        return self.intent_type != "general" and self.confidence >= 0.45


def detect_intent(text: str) -> IntentResult:
    low = text.lower()
    best_type = "general"
    best_family = "general"
    best_score = 0.0
    matches = 0

    for intent_type, (family, groups) in _INTENT_KEYWORDS.items():
        score = 0.0
        hits = 0
        for weight, words in groups:
            for w in words:
                if w in low:
                    score += weight
                    hits += 1
        if score > best_score:
            best_score, best_type, best_family, matches = score, intent_type, family, hits

    if best_score == 0.0:
        is_q = bool(_QUESTION_RE.search(text))
        return IntentResult("general", "general", 0.25 if is_q else 0.1, text.strip())

    # confidence grows with match strength, bonus if phrased as a question/request
    confidence = min(0.55 + 0.12 * best_score, 0.97)
    if _QUESTION_RE.search(text):
        confidence = min(confidence + 0.03, 0.98)
    return IntentResult(best_type, best_family, round(confidence, 2), text.strip())
