"""Application settings. Sensible offline/dev defaults; real integrations via env."""
from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Cue"  # platform name; Sales is one Copilot Pack
    version: str = "0.3.0"

    # Launch scope — which Copilot Packs are live.
    enabled_packs: str = "sales,tech"

    # URLs (used for OAuth redirects)
    app_base_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:3000"

    # Storage
    database_url: str = "sqlite:///./copilot.db"

    # LLM / embeddings (all optional — offline fallback otherwise)
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-6"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"
    # Agent engine: "auto" picks messages_mcp when an Anthropic key is set, else offline.
    agent_engine: str = "auto"  # auto | messages_mcp | agent_sdk | offline
    # Cap each connected MCP server to its read/search tools on the live-answer path, so the
    # model isn't handed (and re-billed for, every agentic turn) the full write+admin catalog.
    # Cuts the per-answer tool-definition prefix ~65-75%. Set false to hand over every tool again.
    mcp_tool_allowlist: bool = True
    # Tune the per-provider allowlists without a code change. A JSON object mapping a provider name
    # (github / jira / hubspot / notion / …) to the exact tools to expose: a provider listed here
    # REPLACES its built-in list, an empty list [] leaves that provider unrestricted, and a new
    # provider adds a list. e.g. MCP_TOOL_ALLOWLIST_OVERRIDES='{"hubspot": ["hubspot-search-objects"]}'.
    # Kept as a plain string (parsed defensively in agent/mcp_tools) so an empty or malformed value
    # from the compose env passthrough falls back to "no overrides" instead of crashing startup.
    mcp_tool_allowlist_overrides: str = ""
    # Layer-1 triage model (fast/cheap): decides if a turn needs an answer before the
    # deep agent runs. Falls back to the regex detector when no Anthropic key is set.
    triage_model: str = "claude-haiku-4-5-20251001"
    # Prompt caching: put a cache_control breakpoint on the (stable) system prefix so the
    # tools+system block is read at ~0.1x on repeat calls within the 5-min TTL — big win on the
    # deep-answer path (re-sent every question in a meeting + every agentic turn). Safe: Anthropic
    # silently skips caching for prefixes below the model minimum. Set false to disable everywhere.
    prompt_cache: bool = True

    # Vector DB
    qdrant_url: str | None = None

    # Auth — Google sign-in. When unset, the app runs in single-user DEV mode.
    # Reuses the same Google OAuth app as the Drive/Gmail/Calendar connectors
    # (one client, multiple authorized redirect URIs).
    google_client_id: str | None = None
    google_client_secret: str | None = None
    # Secret for signing our own session JWTs (HS256). Falls back to the token
    # encryption key, then an insecure dev key.
    session_secret: str | None = None

    # Legacy Clerk fields — kept so old .env files still parse. No longer used.
    clerk_secret_key: str | None = None
    clerk_publishable_key: str | None = None
    clerk_jwks_url: str | None = None
    clerk_issuer: str | None = None

    # Per-user OAuth token encryption (Fernet). Auto-generated for dev if unset.
    token_encryption_key: str | None = None

    # Pilot mode: during the pilot every workspace runs on the Enterprise plan (unlimited
    # meetings/connectors, all features). New signups default to it and existing workspaces
    # are upgraded on startup. Set PILOT_MODE=false to return to normal free/paid tiers.
    pilot_mode: bool = True

    # Billing (Stripe). Free plan works with no keys; paid tiers activate when set.
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    stripe_price_pro: str | None = None
    stripe_price_enterprise: str | None = None

    # Observability
    sentry_dsn: str | None = None

    # Rate limiting (per client IP, per minute)
    rate_limit_per_minute: int = 240

    # Realtime fan-out
    redis_url: str | None = None

    # SLAs / behaviour
    response_sla_seconds: float = 3.0
    cors_origins: str = "http://localhost:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def enabled_pack_list(self) -> list[str]:
        return [p.strip() for p in self.enabled_packs.split(",") if p.strip()]

    @property
    def llm_provider(self) -> str:
        if self.anthropic_api_key:
            return "anthropic"
        if self.openai_api_key:
            return "openai"
        return "offline"

    @property
    def embeddings_enabled(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def google_login_enabled(self) -> bool:
        """Real Google sign-in is on when a Google OAuth app is configured."""
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def dev_mode(self) -> bool:
        """No auth provider configured → single seeded dev user, no JWT required."""
        return not self.google_login_enabled

    @property
    def session_signing_secret(self) -> str:
        return self.session_secret or self.token_encryption_key or "copilot-dev-insecure-key"

    @property
    def billing_enabled(self) -> bool:
        """Real Stripe billing on. Off → dev free-plan mode (upgrades applied directly)."""
        return bool(self.stripe_secret_key)

    @property
    def default_org_plan(self) -> str:
        """Plan a brand-new workspace starts on. Enterprise during the pilot, else free."""
        return "enterprise" if self.pilot_mode else "free"

    @property
    def resolved_agent_engine(self) -> str:
        if self.agent_engine != "auto":
            return self.agent_engine
        return "messages_mcp" if self.anthropic_api_key else "offline"

    @property
    def use_agent_sdk(self) -> bool:
        return self.resolved_agent_engine == "agent_sdk"

    def connector_env(self, provider: str, key: str) -> str | None:
        """Read a per-connector env var, e.g. connector_env('hubspot', 'CLIENT_ID')."""
        return os.getenv(f"{provider.upper()}_{key.upper()}")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
