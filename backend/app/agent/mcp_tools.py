"""Per-provider MCP tool allowlists for the live-answer path.

The native MCP connector injects EVERY tool from every connected server into the model's
context, and the agentic loop re-reads that whole tool-definition block on each internal turn —
the dominant cost of a live answer (a full GitHub + Jira/Confluence catalog is ~40-60K tokens,
re-read 4-5x → ~$0.6 on Sonnet). Live answers only ever READ to answer — writes go through the
post-meeting planner, never `run_turn` — so we cap each server to its read/search tools via the
connector's `tool_configuration.allowed_tools`. This cuts the tool-definition prefix ~65-75% with
no loss of answering ability, and the saving multiplies across every agentic turn.

Keyed by the server's provider name (`conn.provider`). Custom (user-added) servers are left
unrestricted — the user pointed Cue at those deliberately. Providers whose exact hosted tool
names aren't yet confirmed (hubspot, notion) are intentionally omitted: a guessed-wrong name in
an allowlist silently disables that tool, so we'd rather leave those unrestricted than risk
breaking an answer.

The lists below are defaults — tune them without a code change via settings.mcp_tool_allowlist_overrides
(env `MCP_TOOL_ALLOWLIST_OVERRIDES`): a provider listed there replaces its default, an empty list
leaves that provider unrestricted, and a new provider (e.g. hubspot/notion once confirmed) adds one.
"""
from __future__ import annotations

import json
import logging

from ..config import settings

log = logging.getLogger("copilot.mcp_tools")


def _overrides() -> dict[str, list[str]]:
    """Parse settings.mcp_tool_allowlist_overrides (JSON) defensively.

    Empty / whitespace / malformed → {} (never raises), so a bad env value degrades to "no
    overrides" instead of taking the backend down at startup.
    """
    raw = (settings.mcp_tool_allowlist_overrides or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("expected a JSON object")
        return {str(k).lower(): list(v or []) for k, v in data.items()}
    except (ValueError, TypeError) as exc:  # malformed JSON / wrong shape
        log.warning("ignoring invalid MCP_TOOL_ALLOWLIST_OVERRIDES: %s", exc)
        return {}

# Read/search tools only — the live-answer agent never writes.
_READ_TOOLS: dict[str, list[str]] = {
    "github": [
        "get_me",
        "search_repositories", "search_code", "search_issues",
        "search_pull_requests", "search_users", "search_orgs",
        "get_issue", "list_issues", "get_issue_comments",
        "get_pull_request", "list_pull_requests", "get_pull_request_files",
        "get_pull_request_diff", "get_pull_request_comments",
        "get_pull_request_reviews", "get_pull_request_status",
        "get_file_contents", "get_commit", "list_commits",
        "list_branches", "list_tags",
        "list_workflow_runs", "get_workflow_run", "list_workflow_jobs", "get_job_logs",
        "list_releases", "get_latest_release",
        "list_discussions", "get_discussion",
    ],
    # Atlassian remote MCP (Jira + Confluence live behind the same server).
    "jira": [
        "atlassianUserInfo", "getAccessibleAtlassianResources",
        "searchJiraIssuesUsingJql", "getJiraIssue", "getVisibleJiraProjects",
        "getJiraProjectIssueTypesMetadata", "getTransitionsForJiraIssue",
        "getJiraIssueRemoteIssueLinks", "lookupJiraAccountId",
        "getConfluenceSpaces", "getConfluencePage", "getPagesInConfluenceSpace",
        "searchConfluenceUsingCql", "getConfluencePageFooterComments",
        "getConfluencePageInlineComments", "getConfluencePageDescendants",
        "search", "fetch",
    ],
    "confluence": [
        "atlassianUserInfo", "getAccessibleAtlassianResources",
        "getConfluenceSpaces", "getConfluencePage", "getPagesInConfluenceSpace",
        "searchConfluenceUsingCql", "getConfluencePageFooterComments",
        "getConfluencePageInlineComments", "getConfluencePageDescendants",
        "search", "fetch",
    ],
}


def effective_allowlist() -> dict[str, list[str]]:
    """Built-in read/search lists merged with settings.mcp_tool_allowlist_overrides.

    An override REPLACES a provider's list (retune or add a provider); mapping a provider to an
    empty list leaves it unrestricted. Keys are matched case-insensitively.
    """
    merged: dict[str, list[str]] = {k: list(v) for k, v in _READ_TOOLS.items()}
    merged.update(_overrides())
    return merged


def tool_config_for(server: dict) -> dict | None:
    """The `tool_configuration` for a server's MCP payload, or None to leave it unrestricted.

    Restricts a provider to its (possibly overridden) read/search tools; returns None for custom
    servers, unlisted providers, providers overridden to [], or when the allowlist is disabled.
    """
    if not settings.mcp_tool_allowlist or server.get("custom"):
        return None
    allowed = effective_allowlist().get(str(server.get("name", "")).lower())
    if not allowed:
        return None
    return {"enabled": True, "allowed_tools": allowed}
