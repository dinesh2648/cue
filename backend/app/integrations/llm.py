"""LLM + embedding access with a fully offline fallback.

- Generation: Anthropic (preferred) or OpenAI if a key is configured, else `None`
  so callers fall back to the deterministic composer.
- Embeddings: OpenAI if configured, else `None` so the retriever falls back to
  its built-in TF-IDF cosine index.

All network calls are bounded by a timeout and never raise to the caller.
"""
from __future__ import annotations

import logging

import httpx

from ..config import settings

log = logging.getLogger("copilot.llm")

_TIMEOUT = httpx.Timeout(20.0, connect=5.0)


async def llm_complete(
    system: str,
    user: str,
    *,
    max_tokens: int = 800,
    temperature: float = 0.2,
) -> str | None:
    """Return generated text, or None if no provider is configured / call fails."""
    provider = settings.llm_provider
    try:
        if provider == "anthropic":
            return await _anthropic(system, user, max_tokens, temperature)
        if provider == "openai":
            return await _openai(system, user, max_tokens, temperature)
    except Exception as exc:  # pragma: no cover - network failure path
        log.warning("LLM call failed (%s); using offline fallback: %s", provider, exc)
    return None


async def _anthropic(system: str, user: str, max_tokens: int, temperature: float) -> str:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.anthropic_api_key or "",
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": settings.anthropic_model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
        )
        resp.raise_for_status()
        blocks = resp.json().get("content", [])
        return "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()


async def _openai(system: str, user: str, max_tokens: int, temperature: float) -> str:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json={
                "model": settings.openai_model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()


async def embed_texts(texts: list[str]) -> list[list[float]] | None:
    """Return embeddings via OpenAI, or None to signal the local retriever fallback."""
    if not settings.embeddings_enabled or not texts:
        return None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={"model": settings.embedding_model, "input": texts},
            )
            resp.raise_for_status()
            return [item["embedding"] for item in resp.json()["data"]]
    except Exception as exc:  # pragma: no cover
        log.warning("Embedding call failed; using local index: %s", exc)
        return None
