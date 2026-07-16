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
breaking an answer. Add them here once their live tool names are confirmed (a one-line addition).
"""
from __future__ import annotations

from ..config import settings

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


def tool_config_for(server: dict) -> dict | None:
    """The `tool_configuration` for a server's MCP payload, or None to leave it unrestricted.

    Restricts a known built-in provider to its read/search tools; returns None for custom
    servers, unlisted providers, or when the allowlist is disabled (settings.mcp_tool_allowlist).
    """
    if not settings.mcp_tool_allowlist or server.get("custom"):
        return None
    allowed = _READ_TOOLS.get(str(server.get("name", "")).lower())
    if not allowed:
        return None
    return {"enabled": True, "allowed_tools": allowed}
