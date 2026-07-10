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

# A question/request STARTER (works even when the ASR drops the '?'). Allows a few
# leading fillers ("so", "ok", "hey", "quick question") before the interrogative.
# Human-readable intent taxonomy — used to prompt the LLM triage layer (triage.py).
INTENT_DESCRIPTIONS: dict[str, str] = {
    "contract_status": "status of the contract / MSA / signature / paperwork",
    "implementation_eta": "implementation timeline, go-live or onboarding ETA",
    "open_tickets": "open support tickets, issues, incidents or escalations",
    "security_review": "security, SOC 2, compliance, pentest, encryption, data residency",
    "proposal_request": "a request to send a proposal, SOW, deck, quote or one-pager",
    "pricing": "pricing, discounts, cost, budget, licensing or seats",
    "renewal": "renewal, expiration or contract-term extension",
    "product_capability": "product features, integrations, API, limits or 'can it do X'",
    "general": "any other genuine question or research the rep should answer",
}


# Tech Copilot intent taxonomy (used by the Tech pack's LLM triage).
TECH_INTENT_DESCRIPTIONS: dict[str, str] = {
    "requirements": "a feature request, requirement, user story or scope to capture",
    "bug_incident": "a bug, error, incident or production issue",
    "architecture": "system design, architecture, data model or technical approach",
    "integration_api": "an API, integration, webhook, SDK or third-party connection",
    "ticket_status": "status of a Jira ticket, sprint, epic or work item",
    "repo_pr": "a repository, pull request, branch, code change or deployment",
    "security_tech": "security, auth, permissions or compliance from an engineering angle",
    "general": "any other genuine technical question or research the engineer should answer",
}


def family_for(intent_type: str) -> str:
    entry = _INTENT_KEYWORDS.get(intent_type)
    return entry[0] if entry else "general"


_QUESTION_START_RE = re.compile(
    r"^\s*(?:so|and|ok|okay|um|uh|hey|hi|hello|sorry|also|but|well|now|yeah|right|just|"
    r"quick question)*[\s,.-]*"
    r"(what|whats|what's|when|where|why|how|hows|how's|who|whom|whose|which|"
    r"can|could|would|will|do|does|did|is|are|was|were|should|shall|may|might|have|has|had|am)\b",
    re.IGNORECASE,
)

# Explicit requests / info-needs anywhere in the utterance.
_REQUEST_RE = re.compile(
    r"\b(can you|could you|would you|can we|could we|will you|are you able|do you have|"
    r"tell me|let me know|let us know|walk me through|show me|give me|send me|send over|"
    r"share (the|your|that|it|a|some)|i need|we need|i'd like|we'd like|i want|we want|"
    r"looking for|find out|look up|research|explain|summari[sz]e|what's|whats|how's|hows|"
    r"want to (know|understand|see)|need to (know|understand|see)|wondering|"
    r"worried about|concerned about|any (update|flexibility|chance|news))\b",
    re.IGNORECASE,
)

# Pure pleasantries / greetings — suppressed even if they parse as a question
# ("hey, how are you?"). A real ask alongside the greeting still fires (via _REQUEST_RE).
_SMALLTALK_RE = re.compile(
    r"^\s*(hi\b|hey\b|hello\b|yo\b|good\s+(morning|afternoon|evening)|"
    r"how\s+are\s+you|how're\s+you|how\s+are\s+things|how'?s\s+it\s+going|how\s+have\s+you\s+been|"
    r"how\s+are\s+we|how\s+are\s+you\s+doing|how\s+is\s+everything|how'?s\s+everything|"
    r"how\s+was\s+your\s+(weekend|day|week|holiday|vacation|trip|break|morning|evening|night)|"
    r"hope\s+(you|all|everything|things|it|your|you're|youre|u|we|i)\b|"
    r"trust\s+(you|all|everything|things|you're|youre|this)\b|"
    r"long\s+time|good\s+to\s+hear|nice\s+to\s+hear|glad\s+to\s+hear|"
    r"nice\s+to\s+(meet|see)|(great|good|lovely|pleasure)\s+to\s+(see|meet|be)|"
    r"thanks\b|thank\s+you|cheers\b|bye\b|goodbye\b|take\s+care|have\s+a\s+(great|good|nice))",
    re.IGNORECASE,
)

# Meeting LOGISTICS / audio-video checks — never a question for the copilot, so suppress even
# though they parse as "can you …" requests. ("can you hear me?", "you're on mute", "say that again")
_LOGISTICS_RE = re.compile(
    r"\b(can you hear|can you see|do you see|can everyone (see|hear)|you hear me|hear me|"
    r"see my screen|seeing my screen|sharing my screen|screen share|on mute|you'?re? muted|"
    r"i'?m muted|un ?mute|lost you|you cut out|cutting out|breaking up|frozen|"
    r"say that again|come again|can you repeat|repeat that|didn'?t catch)\b",
    re.IGNORECASE,
)

# Interpersonal asides directed at a participant — not questions for the copilot ("Amir, sorry,
# did you want that?", "over to you"). Suppressed unless a genuine request rides along (_REQUEST_RE).
_ASIDE_RE = re.compile(
    r"\b(sorry|did you want|do you want|you want (that|this|it|me to)|are you there|you there|"
    r"you with us|still there|you okay|you good|all good|go ahead|over to you|after you|go on|"
    r"my bad|no worries|one sec|hang on|bear with)\b",
    re.IGNORECASE,
)


def _needs_answer(text: str) -> bool:
    """True only when the utterance is an actual question or request for info/action —
    not a statement, acknowledgement, or pleasantry. Tolerant of missing punctuation."""
    t = text.strip()
    low = t.lower()
    if len(t.split()) < 3:
        return False
    if _LOGISTICS_RE.search(low):  # audio/video/logistics — never for the copilot
        return False
    has_signal = ("?" in t) or bool(_QUESTION_START_RE.match(t)) or bool(_REQUEST_RE.search(low))
    if not has_signal:
        return False
    # "hey, how are you?" / "hope you're doing well?" — parse as questions but are small talk
    # with no real ask. A genuine request alongside the greeting still fires (via _REQUEST_RE).
    if _SMALLTALK_RE.match(low) and not _REQUEST_RE.search(low) and len(t.split()) <= 12:
        return False
    # Interpersonal asides / logistics ("did you want that?", "can you hear me?") — not for the AI.
    if _ASIDE_RE.search(low) and not _REQUEST_RE.search(low) and len(t.split()) <= 14:
        return False
    return True


@dataclass
class IntentResult:
    intent_type: str
    family: str
    confidence: float
    query_text: str

    @property
    def actionable(self) -> bool:
        # Only questions/requests cross 0.45. Topic mentioned in a statement (0.3),
        # greetings / chit-chat (0.1) do NOT trigger a suggestion.
        return self.confidence >= 0.45


def detect_intent(text: str) -> IntentResult:
    low = text.lower()
    best_type = "general"
    best_family = "general"
    best_score = 0.0

    for intent_type, (family, groups) in _INTENT_KEYWORDS.items():
        score = 0.0
        for weight, words in groups:
            for w in words:
                if w in low:
                    score += weight
        if score > best_score:
            best_score, best_type, best_family = score, intent_type, family

    needs = _needs_answer(text)

    if best_score > 0.0:
        # A sales topic surfaced. Only answer when it's actually being asked/requested —
        # a passing mention in a statement ("the contract's signed") shouldn't interrupt.
        if not needs:
            return IntentResult(best_type, best_family, 0.3, text.strip())
        confidence = min(0.6 + 0.12 * best_score, 0.98)
        return IntentResult(best_type, best_family, round(confidence, 2), text.strip())

    # No sales keyword. A genuine general question/request → answer (Claude + web);
    # statements / chit-chat → stay quiet.
    if needs:
        return IntentResult("general", "general", 0.5, text.strip())
    return IntentResult("general", "general", 0.1, text.strip())
