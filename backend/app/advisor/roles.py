"""Role- and department-aware tool policy (the generic advisor's routing brain).

One advisor serves every department; the employee's `team` (department) decides which connected
sources are RELEVANT to them, so we retrieve from — and let the model call — only those. This is
how "Jira is for the tech team only" becomes a rule instead of a hardcoded pack, and how the same
engine stays meaningful for sales, ops, finance, HR, marketing and CS.
"""
from __future__ import annotations

from ..models import User

# Canonical departments. Unknown/empty falls back to "sales" (the historical default).
DEPARTMENTS = ["sales", "tech", "ops", "finance", "hr", "marketing", "cs"]

_LABEL = {
    "sales": "Sales", "tech": "Engineering", "ops": "Operations", "finance": "Finance",
    "hr": "People / HR", "marketing": "Marketing", "cs": "Customer Success",
}

# Sources every employee benefits from — personal comms + shared knowledge + calendar.
_BASE_TOOLS = {"gmail", "google_drive", "google_calendar", "notion", "slack"}

# Extra sources unlocked per department. Jira/GitHub are ENGINEERING-ONLY (per product decision);
# HubSpot/CRM is for customer-facing roles. Everyone keeps the base set above.
_DEPT_EXTRA = {
    "tech": {"jira", "github", "confluence"},
    "sales": {"hubspot"},
    "cs": {"hubspot"},
    "ops": {"hubspot"},
    "finance": {"hubspot"},
    "marketing": {"hubspot"},
    "hr": set(),
}


def department_of(user: User | None) -> str:
    d = (getattr(user, "team", "") or "").lower()
    return d if d in DEPARTMENTS else "sales"


def department_label(user: User | None) -> str:
    return _LABEL.get(department_of(user), "Sales")


def allowed_providers(user: User | None) -> set[str]:
    """The connector/provider keys relevant to this employee's department."""
    return _BASE_TOOLS | _DEPT_EXTRA.get(department_of(user), {"hubspot"})


# Map a server display name (from active_mcp_servers) to a provider key for the policy check.
_NAME_TO_PROVIDER = {
    "github": "github", "jira": "jira", "atlassian": "jira", "confluence": "confluence",
    "hubspot": "hubspot", "notion": "notion", "slack": "slack", "gmail": "gmail",
    "google drive": "google_drive", "drive": "google_drive", "google calendar": "google_calendar",
}


def _provider_of(server_name: str) -> str:
    n = (server_name or "").strip().lower()
    for key, prov in _NAME_TO_PROVIDER.items():
        if key in n:
            return prov
    return n.replace(" ", "_")


def filter_servers_for_role(user: User | None, servers: list[dict]) -> list[dict]:
    """Drop remote-MCP servers that aren't relevant to this employee's department (e.g. Jira for a
    salesperson) so the advisor doesn't waste calls on — or surface — off-role sources.

    Custom (user-added) MCP servers are always kept: the user pointed Cue at them deliberately,
    so they're in-scope by choice regardless of department."""
    allow = allowed_providers(user)
    kept = [s for s in servers if s.get("custom") or _provider_of(s.get("name", "")) in allow]
    return kept


def role_directive(user: User | None) -> str:
    """One line telling the model which sources are in-scope for this role — reinforces the filter
    at the prompt level so it never claims access to an off-role system."""
    dept = department_label(user)
    if department_of(user) == "tech":
        return (f"This employee is in {dept}: engineering sources (Jira, GitHub, Confluence) and "
                "docs/comms are in scope; do not pull CRM/sales data unless explicitly asked.")
    return (f"This employee is in {dept}: CRM (HubSpot), docs, email, calendar and chat are in "
            "scope; engineering trackers (Jira/GitHub) are NOT their tools — don't use them.")
