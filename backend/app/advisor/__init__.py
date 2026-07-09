"""The AI Meeting Advisory Agent — a multi-agent system.

Greenfield home for the advisory intelligence, built as cooperating agents rather than one
prompt. Phase 1 lays the CONTEXT FOUNDATION every other agent depends on:

- profiles: the employee's personal context + the company profile, injected into EVERY request
- roles:    which tools/sources are relevant for this person's department (generic, role-driven)
- meeting_context: the evolving meeting state (running summary, topics, decisions, entities)

Core principle (never violated): the advisor answers nothing in isolation — every response is
grounded in user profile + role + company profile + meeting context + retrieved knowledge, and
never fabricates beyond what those sources support.
"""
