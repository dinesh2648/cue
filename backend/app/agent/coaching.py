"""Rep coaching scorecard — analyze how the sales rep handled a call.

Combines objective transcript metrics (talk ratio, questions asked, fillers, longest
monologue) with an LLM review that scores the rep across coaching dimensions and gives
specific, quote-backed improvement tips. The rep is identified by speaker name (the live
capture maps everyone to `customer`, so role can't be relied on).
"""
from __future__ import annotations

import json
import re

from ..integrations.llm import llm_complete

_FILLERS = re.compile(r"\b(um+|uh+|er+|like|you know|sort of|kind of|basically|literally|i mean)\b", re.IGNORECASE)

_DIMENSIONS = [
    "Discovery & Questioning",
    "Listening & Talk Ratio",
    "Objection Handling",
    "Answer Quality & Accuracy",
    "Rapport & Tone",
    "Next Steps & Closing",
]

_SYSTEM = (
    "You are an expert sales coach reviewing a recorded customer call. Analyze how the REP "
    "(named below) handled it — NOT the customer. Be specific, fair, and grounded in the "
    "transcript; cite short quotes as evidence. Use the objective metrics provided to inform "
    "scores (e.g. a very high talk ratio hurts 'Listening').\n"
    "Return ONLY a JSON object:\n"
    "{\n"
    '  "overall_score": <0-100 integer>,\n'
    '  "headline": "<one-sentence verdict>",\n'
    '  "dimensions": [{"name": "<one of the given dimensions>", "score": <0-100>, "comment": "<1-2 sentences, specific>"}],\n'
    '  "strengths": ["<specific thing the rep did well>", ...],\n'
    '  "improvements": ["<specific, actionable area to improve>", ...],\n'
    '  "coaching_tips": [{"tip": "<concrete coaching tip>", "example": "<what to say / a better phrasing>"}]\n'
    "}\n"
    f"Score EACH of these dimensions: {', '.join(_DIMENSIONS)}. "
    "Keep every item concise. JSON only, no markdown."
)


def _is_rep(speaker: str, rep_name: str) -> bool:
    if not speaker or not rep_name:
        return False
    s, r = speaker.lower().strip(), rep_name.lower().strip()
    if s in r or r in s:
        return True
    sp, rp = s.split(), r.split()
    return bool(sp and rp and sp[0] == rp[0])  # same first name


def metrics(segments: list[dict], rep_name: str) -> dict:
    rep_words = cust_words = rep_turns = cust_turns = rep_qs = cust_qs = longest = fillers = 0
    for seg in segments:
        text = seg.get("text", "") or ""
        wc = len(text.split())
        if _is_rep(seg.get("speaker", ""), rep_name):
            rep_words += wc
            rep_turns += 1
            longest = max(longest, wc)
            if "?" in text:
                rep_qs += 1
            fillers += len(_FILLERS.findall(text))
        else:
            cust_words += wc
            cust_turns += 1
            if "?" in text:
                cust_qs += 1
    total = rep_words + cust_words or 1
    return {
        "talk_ratio_pct": round(100 * rep_words / total),
        "rep_turns": rep_turns,
        "customer_turns": cust_turns,
        "rep_questions": rep_qs,
        "customer_questions": cust_qs,
        "longest_monologue_words": longest,
        "filler_count": fillers,
        "total_words": total,
    }


def _context(meeting: dict, transcript: str, m: dict) -> str:
    return (
        f"REP under review: {meeting.get('rep_name', 'the rep')}\n"
        f"Customer: {meeting.get('customer_company') or meeting.get('customer_contact') or 'the customer'}\n\n"
        f"OBJECTIVE METRICS:\n"
        f"  rep talk ratio: {m['talk_ratio_pct']}% of words (rep {m['rep_turns']} turns / customer {m['customer_turns']} turns)\n"
        f"  questions the rep asked: {m['rep_questions']}; questions the customer asked: {m['customer_questions']}\n"
        f"  longest rep monologue: {m['longest_monologue_words']} words; filler words: {m['filler_count']}\n\n"
        f"TRANSCRIPT:\n{transcript[:11000]}"
    )


def _as_list(v):
    return [x for x in v if x] if isinstance(v, list) else []


async def generate_scorecard(meeting: dict, segments: list[dict], transcript: str) -> dict | None:
    """Return a structured rep scorecard, or None if the transcript is too thin / no LLM."""
    rep = meeting.get("rep_name") or "the rep"
    m = metrics(segments, rep)
    if m["total_words"] < 40:  # not enough was said to coach on
        return None

    raw = await llm_complete(
        system=_SYSTEM, user=_context(meeting, transcript, m),
        max_tokens=1700, temperature=0.3, timeout=60.0,
    )
    if not raw:
        return None
    try:
        p = json.loads(raw[raw.find("{") : raw.rfind("}") + 1])
    except (ValueError, json.JSONDecodeError):
        return None

    try:
        overall = int(p.get("overall_score") or 0)
    except (TypeError, ValueError):
        overall = 0
    dims = [
        {"name": str(d.get("name", "")), "score": int(d.get("score") or 0), "comment": str(d.get("comment", ""))}
        for d in (p.get("dimensions") or []) if isinstance(d, dict)
    ]
    tips = [
        {"tip": str(t.get("tip", "")), "example": str(t.get("example", ""))}
        for t in (p.get("coaching_tips") or []) if isinstance(t, dict)
    ]
    return {
        "rep_name": rep,
        "overall_score": max(0, min(100, overall)),
        "headline": str(p.get("headline", "")).strip(),
        "dimensions": dims,
        "strengths": _as_list(p.get("strengths")),
        "improvements": _as_list(p.get("improvements")),
        "coaching_tips": tips,
        "metrics": m,
    }
