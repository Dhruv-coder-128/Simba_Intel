"""Cyber Max's real implementation: a virtual model backed by a pool of real
(provider, actual_model) pairs, tried in priority order, entirely inside one
request - the user only ever sees "Cyber Max"; which real model answered is
an internal, per-request decision that's never surfaced to them.

This is a provider in the same sense GroqProvider/MistralProvider are (same
BaseProvider contract), so every existing call site - chat/services/
ai_router.py, chat/views.py's ask_ai/regenerate_message/edit_message/
continue_message - needs zero changes: they already just resolve
`get_model_config(model_id)` to a (provider, actual_model) pair and call
`get_provider(config.provider).chat_stream(messages, config.actual_model,
**kwargs)` generically. Registering "virtual" as a provider name (see
chat/services/provider_manager.py's PROVIDER_REGISTRY) and pointing
MODEL_REGISTRY["cyber-max"] at it is the entire integration.

Adding a model to Cyber Max's pool, reordering its priority, or adding a
brand-new virtual model entirely is a one-place edit to MODEL_POOLS below -
no routing code changes. Adding a future provider (Mistral, Gemini,
OpenRouter, Ollama, HuggingFace) to a pool is exactly the same one-line
change, since every pool member is dispatched through the existing
get_provider(member.provider) - this file never hardcodes "groq" anywhere
except inside the pool data itself.
"""
import logging
import time
from dataclasses import dataclass
from typing import Dict, Generator, List, Optional

from django.core.cache import cache

from chat.providers.base import BaseProvider
from chat.services.provider_manager import get_provider

logger = logging.getLogger("simba_intel")

# How long a model that just returned a rate-limit/quota signal is skipped
# for - see the module docstring and _mark_cooldown/_is_cooling_down below.
RATE_LIMIT_COOLDOWN_SECONDS = 60

# Retries per pool model on a transient (non-rate-limit) failure: 1 initial
# attempt + 1 retry = 2 total. A rate-limited model is never retried within
# the same request (see _handle_failure) - only skipped and cooled down.
ATTEMPTS_PER_MODEL = 2

_CACHE_KEY_PREFIX = "virtual_router_cooldown"


@dataclass(frozen=True)
class PoolMember:
    provider: str
    model: str
    priority: int


# ================= Centralized virtual model pools =================
# Keyed by the "pool key" that a virtual ModelConfig's actual_model points
# at (see chat/services/model_registry.py's "cyber-max" entry) - not by the
# visible model id itself, so a future visible model could share a pool, or
# have its own, without any naming collision. Ordered by priority ascending
# (1 = tried first). All Groq-hosted today; a pool member's `provider` is
# read the same way any other provider name is (chat/services/
# provider_manager.get_provider), so a Mistral/Gemini/OpenRouter/Ollama/
# HuggingFace member is a data-only addition once that provider is
# integrated - see the module docstring.
MODEL_POOLS: Dict[str, List[PoolMember]] = {
    "cyber-max-pool": [
        # Priority 1: the model Cyber Max has always pointed to - keeping it
        # first means the common (all-healthy) case behaves identically to
        # before this router existed.
        PoolMember(provider="groq", model="openai/gpt-oss-120b", priority=1),
        PoolMember(provider="groq", model="qwen/qwen3-32b", priority=2),
        PoolMember(provider="groq", model="openai/gpt-oss-20b", priority=3),
        PoolMember(provider="groq", model="llama-3.3-70b-versatile", priority=4),
        PoolMember(provider="groq", model="llama-3.1-8b-instant", priority=5),
        PoolMember(provider="groq", model="allam-2-7b", priority=6),
    ],
}


def _cooldown_key(provider: str, model: str) -> str:
    return f"{_CACHE_KEY_PREFIX}:{provider}:{model}"


def _is_cooling_down(provider: str, model: str) -> bool:
    return cache.get(_cooldown_key(provider, model)) is not None


def _mark_cooldown(provider: str, model: str, seconds: int = RATE_LIMIT_COOLDOWN_SECONDS) -> None:
    """Uses Django's cache framework (not a plain module-level dict) so this
    automatically becomes cross-process/cross-worker the moment a shared
    backend (e.g. Redis) is configured via CACHES - today, with the default
    LocMemCache, it's per-process, same as a plain dict would be, but
    nothing here needs to change to pick up the stronger guarantee later."""
    cache.set(_cooldown_key(provider, model), True, timeout=seconds)


def _is_rate_limit_error(exc: Exception) -> bool:
    """True for anything meaning 'this model/account is throttled right
    now' - the Health System's trigger for a cooldown. Checked by exception
    type name first (groq.RateLimitError today; any future provider's own
    rate-limit exception class name would need adding here), then by
    status_code, then by message content as a last resort, since not every
    SDK raises a distinctly-typed rate-limit exception."""
    if type(exc).__name__ == "RateLimitError":
        return True
    if getattr(exc, "status_code", None) == 429:
        return True
    text = str(exc).lower()
    return any(kw in text for kw in ("rate limit", "rate_limit", "quota", "too many requests"))


def _is_transient_error(exc: Exception) -> bool:
    """True for timeouts/connection failures/5xx - worth one retry on the
    same model, unlike a rate limit (see _is_rate_limit_error), since
    there's a real chance the very next attempt succeeds. Used only to
    label the reason in logs; the retry itself happens unconditionally for
    any non-rate-limit failure (see chat_stream/chat below)."""
    if type(exc).__name__ in ("APITimeoutError", "Timeout", "APIConnectionError", "InternalServerError"):
        return True
    status_code = getattr(exc, "status_code", None)
    if status_code is not None and status_code >= 500:
        return True
    text = str(exc).lower()
    return any(kw in text for kw in ("timeout", "timed out", "temporarily unavailable", "connection"))


def _failure_reason(exc: Exception) -> str:
    if _is_rate_limit_error(exc):
        return "rate_limit"
    if _is_transient_error(exc):
        return "transient"
    return "error"


class VirtualRouterProvider(BaseProvider):
    """A BaseProvider that routes to other providers instead of calling any
    API of its own - see the module docstring for the full picture."""

    provider_name = "virtual"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.supported_models = list(MODEL_POOLS.keys())

    def _initialize_client(self):
        # No client of its own: every real call is delegated to the real
        # provider (get_provider(member.provider)) for whichever pool
        # member is currently being tried.
        pass

    def _ordered_pool(self, pool_key: str) -> List[PoolMember]:
        pool = MODEL_POOLS.get(pool_key)
        if not pool:
            raise ValueError(f"Unknown virtual model pool: {pool_key!r}")
        return sorted(pool, key=lambda m: m.priority)

    def _log_failure(self, member: PoolMember, exc: Exception, attempt: int, latency: float) -> None:
        reason = _failure_reason(exc)
        logger.warning(
            "virtual_router model failed: model=%s/%s attempt=%d/%d reason=%s latency=%.2fs error=%s",
            member.provider, member.model, attempt + 1, ATTEMPTS_PER_MODEL, reason, latency, exc,
        )
        if reason == "rate_limit":
            _mark_cooldown(member.provider, member.model)

    def _log_selected(self, pool_key: str, member: PoolMember, latency: float, fallback_count: int) -> None:
        logger.info(
            "virtual_router selected model=%s/%s pool=%s latency=%.2fs fallback_count=%d",
            member.provider, member.model, pool_key, latency, fallback_count,
        )

    def chat(self, messages: list, model: str, **kwargs) -> str:
        last_error: Optional[Exception] = None
        fallback_count = 0
        for member in self._ordered_pool(model):
            if _is_cooling_down(member.provider, member.model):
                continue
            for attempt in range(ATTEMPTS_PER_MODEL):
                start = time.time()
                try:
                    provider = get_provider(member.provider)
                    result = provider.chat(messages, member.model, **kwargs)
                except Exception as e:
                    last_error = e
                    self._log_failure(member, e, attempt, time.time() - start)
                    if _is_rate_limit_error(e):
                        break  # no point retrying an already-rate-limited model
                    continue
                else:
                    self._log_selected(model, member, time.time() - start, fallback_count)
                    return result
            fallback_count += 1
        logger.warning("virtual_router: every pool model unavailable/failed for pool=%s", model)
        raise last_error or RuntimeError(f"No models available in pool {model!r}")

    def chat_stream(
        self, messages: list, model: str, on_usage=None, **kwargs
    ) -> Generator[str, None, None]:
        last_error: Optional[Exception] = None
        fallback_count = 0
        for member in self._ordered_pool(model):
            if _is_cooling_down(member.provider, member.model):
                continue
            for attempt in range(ATTEMPTS_PER_MODEL):
                start = time.time()
                try:
                    provider = get_provider(member.provider)
                    gen = provider.chat_stream(messages, member.model, on_usage=on_usage, **kwargs)
                    first_chunk = next(gen)
                except StopIteration:
                    # A real, successful call that just produced no tokens -
                    # not a failure, matches chat_stream_with_failover's own
                    # treatment of this exact case one layer up.
                    self._log_selected(model, member, time.time() - start, fallback_count)
                    return
                except Exception as e:
                    last_error = e
                    self._log_failure(member, e, attempt, time.time() - start)
                    if _is_rate_limit_error(e):
                        break  # no point retrying an already-rate-limited model
                    continue
                else:
                    self._log_selected(model, member, time.time() - start, fallback_count)
                    yield first_chunk
                    yield from gen
                    return
            fallback_count += 1
        logger.warning("virtual_router: every pool model unavailable/failed for pool=%s", model)
        raise last_error or RuntimeError(f"No models available in pool {model!r}")

    def vision(self, messages: list, model: str, **kwargs) -> str:
        # Routed through the exact same pool/health/retry machinery as
        # chat() - a pool with no vision-capable member simply fails the
        # same way any non-vision provider's vision() call would.
        return self.chat(messages, model, **kwargs)

    def generate_image(self, prompt: str, model: str, **kwargs) -> str:
        raise NotImplementedError("Image generation is not routed through the virtual model pool.")
