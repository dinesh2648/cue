"""Meeting simulator — the stand-in for the Google Meet bot (FR-001 / FR-002).

A real bot would join the call and stream diarized transcript segments over the
same WebSocket the engine already consumes. Until that integration lands, these
scripted scenarios produce a realistic, diarized sales conversation so the full
copilot pipeline can be exercised end to end.

Each turn: (speaker, role, text, delay_seconds_before_emitting).
"""
from __future__ import annotations

# role: "rep" (our salesperson) | "customer" | "system"
Scenario = list[dict]

NORTHWIND_EXPANSION: Scenario = [
    {"speaker": "Alex Rivera", "role": "rep", "text": "Hi Sarah, thanks for hopping on! Good to see you again. How are things over at Northwind?", "delay": 1.0},
    {"speaker": "Sarah Chen", "role": "customer", "text": "Hey Alex, doing well thanks. We're keen to move forward — before anything else, what's the current status of our contract?", "delay": 3.0},
    {"speaker": "Alex Rivera", "role": "rep", "text": "Great question, let me check on that for you.", "delay": 2.2},
    {"speaker": "Sarah Chen", "role": "customer", "text": "Perfect. And once we sign, what's the ETA for implementation? My team wants to plan around go-live.", "delay": 3.4},
    {"speaker": "Alex Rivera", "role": "rep", "text": "Absolutely, I can walk you through the timeline.", "delay": 2.0},
    {"speaker": "Sarah Chen", "role": "customer", "text": "Our security team is also asking — has the security questionnaire been completed, and can you share your SOC 2 report?", "delay": 3.6},
    {"speaker": "Alex Rivera", "role": "rep", "text": "Of course, security is a top priority for us.", "delay": 2.0},
    {"speaker": "Sarah Chen", "role": "customer", "text": "One more — how many support tickets do we currently have open? We had a couple of issues last month I want to make sure are resolved.", "delay": 3.6},
    {"speaker": "Alex Rivera", "role": "rep", "text": "Let me pull that up for you right now.", "delay": 2.0},
    {"speaker": "Sarah Chen", "role": "customer", "text": "Thanks. Could you also share the latest proposal? I want to bring the updated numbers to my CFO this week.", "delay": 3.4},
    {"speaker": "Alex Rivera", "role": "rep", "text": "Definitely, I'll get that over to you.", "delay": 2.0},
    {"speaker": "Sarah Chen", "role": "customer", "text": "And on pricing — is there any flexibility if we commit to a multi-year deal?", "delay": 3.2},
    {"speaker": "Alex Rivera", "role": "rep", "text": "There's room to work with you there for sure.", "delay": 2.0},
    {"speaker": "Sarah Chen", "role": "customer", "text": "This all sounds great. I think we're aligned — let's aim to get this wrapped up soon.", "delay": 3.0},
    {"speaker": "Alex Rivera", "role": "rep", "text": "Amazing. I'll send everything over right after this call. Thanks Sarah!", "delay": 2.2},
]

SCENARIOS: dict[str, Scenario] = {
    "northwind_expansion": NORTHWIND_EXPANSION,
}

DEFAULT_SCENARIO = "northwind_expansion"


def get_scenario(name: str | None) -> Scenario:
    return SCENARIOS.get(name or DEFAULT_SCENARIO, NORTHWIND_EXPANSION)


def transcript_text(scenario: Scenario) -> str:
    return "\n".join(f"{t['speaker']} ({t['role']}): {t['text']}" for t in scenario)
