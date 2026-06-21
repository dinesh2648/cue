"""Connector catalog: OAuth + remote-MCP config for each provider.

Credentials and MCP URLs come from env (e.g. HUBSPOT_CLIENT_ID, NOTION_MCP_URL).
A connector with no client credentials is shown as "available, not configured".
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from ..config import settings


@dataclass
class OAuthConfig:
    authorize_url: str
    token_url: str
    scopes: list[str]
    extra_authorize_params: dict = field(default_factory=dict)
    token_auth: str = "post"  # "post" = client creds in body | "basic" = HTTP Basic
    refreshable: bool = True
    userinfo_url: str | None = None


@dataclass
class Connector:
    key: str
    name: str
    icon: str
    category: str
    description: str
    oauth: OAuthConfig
    credentials_provider: str  # which *_CLIENT_ID/SECRET env prefix to use
    default_mcp_url: str | None = None


CONNECTORS: dict[str, Connector] = {
    "hubspot": Connector(
        key="hubspot",
        name="HubSpot",
        icon="🟠",
        category="CRM",
        description="Deals, companies, contacts, tickets, notes — your pipeline of record.",
        credentials_provider="hubspot",
        default_mcp_url="https://mcp.hubspot.com/anthropic",
        oauth=OAuthConfig(
            authorize_url="https://app.hubspot.com/oauth/authorize",
            token_url="https://api.hubapi.com/oauth/v1/token",
            scopes=[
                "crm.objects.contacts.read",
                "crm.objects.companies.read",
                "crm.objects.deals.read",
                "tickets",
                "oauth",
            ],
            userinfo_url="https://api.hubapi.com/oauth/v1/access-tokens/",
        ),
    ),
    "google_drive": Connector(
        key="google_drive",
        name="Google Drive",
        icon="📂",
        category="Docs",
        description="Proposals, SOWs, security docs, decks — read-only, your files only.",
        credentials_provider="google",
        default_mcp_url=None,  # set GOOGLE_DRIVE_MCP_URL (self-hosted Drive MCP)
        oauth=OAuthConfig(
            authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",
            scopes=[
                "https://www.googleapis.com/auth/drive.readonly",
                "openid",
                "email",
            ],
            extra_authorize_params={"access_type": "offline", "prompt": "consent"},
            userinfo_url="https://openidconnect.googleapis.com/v1/userinfo",
        ),
    ),
    "gmail": Connector(
        key="gmail",
        name="Gmail",
        icon="✉️",
        category="Email",
        description="Email threads with the customer — for context and follow-up drafts.",
        credentials_provider="google",
        default_mcp_url=None,  # set GMAIL_MCP_URL (self-hosted Gmail MCP)
        oauth=OAuthConfig(
            authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",
            scopes=[
                "https://www.googleapis.com/auth/gmail.readonly",
                "openid",
                "email",
            ],
            extra_authorize_params={"access_type": "offline", "prompt": "consent"},
            userinfo_url="https://openidconnect.googleapis.com/v1/userinfo",
        ),
    ),
    "notion": Connector(
        key="notion",
        name="Notion",
        icon="📓",
        category="Knowledge",
        description="Internal wikis, runbooks, product docs from your Notion workspace.",
        credentials_provider="notion",
        default_mcp_url="https://mcp.notion.com/mcp",
        oauth=OAuthConfig(
            authorize_url="https://api.notion.com/v1/oauth/authorize",
            token_url="https://api.notion.com/v1/oauth/token",
            scopes=[],  # Notion grants access per the integration's configured capabilities
            extra_authorize_params={"owner": "user"},
            token_auth="basic",
            refreshable=False,
        ),
    ),
    "google_calendar": Connector(
        key="google_calendar",
        name="Google Calendar",
        icon="📅",
        category="Calendar",
        description="Your meetings, attendees, and agendas — for prep and scheduling follow-ups.",
        credentials_provider="google",
        default_mcp_url=None,  # set GOOGLE_CALENDAR_MCP_URL (self-hosted Calendar MCP)
        oauth=OAuthConfig(
            authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",
            scopes=[
                "https://www.googleapis.com/auth/calendar.readonly",
                "openid",
                "email",
            ],
            extra_authorize_params={"access_type": "offline", "prompt": "consent"},
            userinfo_url="https://openidconnect.googleapis.com/v1/userinfo",
        ),
    ),
    "linkedin": Connector(
        key="linkedin",
        name="LinkedIn",
        icon="💼",
        category="Social",
        # Honest scope note: standard LinkedIn OAuth only exposes the member's own
        # basic profile. Prospect lookups / connections / messaging require LinkedIn
        # partner APIs (Sales Navigator) or a provider MCP (e.g. Unipile) — point
        # LINKEDIN_MCP_URL at one to unlock richer data.
        description="Your profile and network context (basic by default; richer via a partner/provider MCP).",
        credentials_provider="linkedin",
        default_mcp_url=None,  # set LINKEDIN_MCP_URL (partner/provider MCP)
        oauth=OAuthConfig(
            authorize_url="https://www.linkedin.com/oauth/v2/authorization",
            token_url="https://www.linkedin.com/oauth/v2/accessToken",
            scopes=["openid", "profile", "email"],
            refreshable=False,
            userinfo_url="https://api.linkedin.com/v2/userinfo",
        ),
    ),
}


def client_credentials(provider: str) -> tuple[str | None, str | None]:
    c = CONNECTORS[provider]
    prefix = c.credentials_provider.upper()
    return os.getenv(f"{prefix}_CLIENT_ID"), os.getenv(f"{prefix}_CLIENT_SECRET")


def mcp_url(provider: str) -> str | None:
    c = CONNECTORS[provider]
    return os.getenv(f"{provider.upper()}_MCP_URL") or c.default_mcp_url


def is_configured(provider: str) -> bool:
    cid, csec = client_credentials(provider)
    return bool(cid and csec)


def redirect_uri(provider: str) -> str:
    return f"{settings.app_base_url}/api/connectors/{provider}/callback"
