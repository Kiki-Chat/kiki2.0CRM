"""Centralized OpenAI client for the Kiki copilot + shared classifiers.

Phase 0 — BUILD-ONLY, dormant until OPENAI_API_KEY is set. Mirrors the
``app/core/cache.py`` "ship inert, enable under supervision" pattern:

1. **Disabled by default.** With no ``OPENAI_API_KEY`` the client is ``None``:
   :func:`is_configured` is ``False``, :func:`chat` / :func:`stream_chat` raise a
   clear :class:`AIServiceDisabled`, and callers (e.g. the classifiers) treat that
   as "skip" rather than crash. The app behaves exactly as it does today.
2. **Lazy import.** The ``openai`` package is imported only when a key is present,
   so it isn't required for the app to boot or for unrelated tests to run.
3. **Tests** inject a fake via :func:`set_test_client`.

We use the Chat Completions API (stable, supports streaming + tool calling). The
small/fast ``gpt-4o-mini``-class model is the default (config, env-overridable).
"""
from __future__ import annotations

import logging
from typing import Any, Iterator

from app.core.config import settings

log = logging.getLogger(__name__)


class AIServiceDisabled(RuntimeError):
    """Raised when an OpenAI call is attempted while the service is disabled."""


# Sentinel client states: None = not yet initialised / disabled.
_client: Any = None
_init_done = False
_test_client: Any = None


def set_test_client(client: Any) -> None:
    """Inject a fake OpenAI client (tests only). Pass ``None`` to clear."""
    global _test_client, _client, _init_done
    _test_client = client
    _client = None
    _init_done = False


def _get_client() -> Any:
    """Return a live OpenAI client, or None when the service is disabled."""
    global _client, _init_done
    if _test_client is not None:
        return _test_client
    if _init_done:
        return _client
    _init_done = True
    key = (settings.openai_api_key or "").strip()
    if not key:
        _client = None  # disabled — no OPENAI_API_KEY configured
        return None
    try:
        from openai import OpenAI  # lazy: only needed when AI is actually enabled

        _client = OpenAI(api_key=key, timeout=settings.openai_timeout_seconds)
        log.info(
            "ai: OpenAI client initialised (copilot model=%s)",
            settings.openai_copilot_model,
        )
    except Exception as exc:  # noqa: BLE001 — fail-open: never block startup on AI
        log.warning("ai: OpenAI init failed (%s) — AI features disabled", exc)
        _client = None
    return _client


def is_configured() -> bool:
    """True when a usable OpenAI client is configured (OPENAI_API_KEY set / test client)."""
    return _get_client() is not None


def _build_params(
    messages: list[dict[str, Any]],
    *,
    model: str | None,
    tools: list[dict[str, Any]] | None,
    tool_choice: Any,
    temperature: float,
    extra: dict[str, Any],
) -> dict[str, Any]:
    chosen = model or settings.openai_copilot_model
    params: dict[str, Any] = {"model": chosen, "messages": messages}
    # "Thinking" reasoning models (o1/o3/o4…) reject `temperature` — only send it to
    # the standard chat models.
    if not chosen.startswith(("o1", "o3", "o4")):
        params["temperature"] = temperature
    if tools:
        params["tools"] = tools
        if tool_choice is not None:
            params["tool_choice"] = tool_choice
    params.update(extra)
    return params


def chat(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: Any = None,
    temperature: float = 0.2,
    **kwargs: Any,
) -> Any:
    """Non-streaming chat completion → the raw OpenAI response object.

    Raises :class:`AIServiceDisabled` when no client is configured.
    """
    client = _get_client()
    if client is None:
        raise AIServiceDisabled("OpenAI is not configured (set OPENAI_API_KEY)")
    params = _build_params(
        messages, model=model, tools=tools, tool_choice=tool_choice,
        temperature=temperature, extra=kwargs,
    )
    return client.chat.completions.create(**params)


def stream_chat(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: Any = None,
    temperature: float = 0.2,
    **kwargs: Any,
) -> Iterator[Any]:
    """Streaming chat completion → an iterator of OpenAI streaming chunks.

    Raises :class:`AIServiceDisabled` when no client is configured.
    """
    client = _get_client()
    if client is None:
        raise AIServiceDisabled("OpenAI is not configured (set OPENAI_API_KEY)")
    params = _build_params(
        messages, model=model, tools=tools, tool_choice=tool_choice,
        temperature=temperature, extra=kwargs,
    )
    return client.chat.completions.create(stream=True, **params)


def embed(texts: list[str], *, model: str = "text-embedding-3-small") -> tuple[list[list[float]], int]:
    """Embed ``texts`` → (vectors, total_tokens). Raises :class:`AIServiceDisabled`
    when no client is configured. Used by the case matchmaker for a cheap similarity
    pre-pass so the LLM only adjudicates the borderline groupings."""
    client = _get_client()
    if client is None:
        raise AIServiceDisabled("OpenAI is not configured (set OPENAI_API_KEY)")
    resp = client.embeddings.create(model=model, input=texts)
    vectors = [d.embedding for d in resp.data]
    total = getattr(getattr(resp, "usage", None), "total_tokens", 0) or 0
    return vectors, total
