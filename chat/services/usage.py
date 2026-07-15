"""Usage tracking and rate limiting for Phase 4.

Token counts come from the provider when it supports real usage reporting
(currently: Mistral, via `on_usage` callbacks threaded through chat_stream/
vision - see providers/mistral_provider.py). Every other case (Groq chat,
Pollinations images) falls back to a character-count heuristic
(`len(text) / 4`, ~4 chars per English token) - close enough for a cost
estimate, not intended as an exact figure. `tokens_are_estimated` on
UsageEvent records which one happened so the analytics UI can label it.
"""
from datetime import timedelta
from typing import Optional

from django.utils import timezone

from chat.models import UsageEvent
from chat.services.cost_table import estimate_cost

RATE_LIMIT_WINDOW_MINUTES = 1
RATE_LIMIT_MAX_REQUESTS = 30


def estimate_tokens(text: str) -> int:
    text = text or ""
    if not text:
        return 0
    return max(1, len(text) // 4)


def record_usage(
    user,
    session,
    provider: str,
    model_id: str,
    event_type: str,
    prompt_text: str = "",
    completion_text: str = "",
    captured_usage: Optional[dict] = None,
    latency: Optional[float] = None,
) -> UsageEvent:
    """Create a UsageEvent. `captured_usage` (if provided and non-empty) is
    real {"prompt_tokens":..,"completion_tokens":..} data from the provider;
    otherwise tokens are estimated from the raw text."""
    if captured_usage and captured_usage.get("prompt_tokens") is not None:
        prompt_tokens = captured_usage.get("prompt_tokens") or 0
        completion_tokens = captured_usage.get("completion_tokens") or 0
        estimated = False
    else:
        prompt_tokens = estimate_tokens(prompt_text)
        completion_tokens = estimate_tokens(completion_text)
        estimated = True

    cost = estimate_cost(model_id, prompt_tokens, completion_tokens)

    return UsageEvent.objects.create(
        user=user,
        session=session,
        provider=provider,
        model_id=model_id,
        event_type=event_type,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        estimated_cost_usd=cost,
        tokens_are_estimated=estimated,
        latency=latency,
    )


def check_rate_limit(user) -> bool:
    """True if `user` is still under the sliding-window request cap."""
    cutoff = timezone.now() - timedelta(minutes=RATE_LIMIT_WINDOW_MINUTES)
    count = UsageEvent.objects.filter(user=user, created_at__gte=cutoff).count()
    return count < RATE_LIMIT_MAX_REQUESTS
