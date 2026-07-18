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
from typing import Optional, Tuple

from django.db.models import F, Sum
from django.utils import timezone

from chat.models import UsageEvent, UserProfile
from chat.services.cost_table import estimate_cost

RATE_LIMIT_WINDOW_MINUTES = 1
RATE_LIMIT_MAX_REQUESTS = 30

# event_type -> (UserProfile field name, human label for the error message)
DAILY_LIMIT_FIELDS = {
    "chat": ("daily_chat_limit", "chat messages"),
    "image": ("daily_image_limit", "image generations"),
    "vision": ("daily_vision_limit", "Vision requests"),
}


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


def record_failure(user, session, provider: str, model_id: str, event_type: str, latency: Optional[float] = None) -> UsageEvent:
    """Part 7 (AI Analytics) - the failure-side counterpart to record_usage,
    used so success/error rate reflects real outcomes instead of being
    unavailable. Zero tokens/cost (nothing was actually generated) and
    success=False, which check_rate_limit/check_daily_limit both explicitly
    exclude - a failed call must never consume the user's quota."""
    return UsageEvent.objects.create(
        user=user,
        session=session,
        provider=provider,
        model_id=model_id,
        event_type=event_type,
        prompt_tokens=0,
        completion_tokens=0,
        estimated_cost_usd=0,
        tokens_are_estimated=False,
        latency=latency,
        success=False,
    )


def check_rate_limit(user) -> bool:
    """True if `user` is still under the sliding-window request cap."""
    cutoff = timezone.now() - timedelta(minutes=RATE_LIMIT_WINDOW_MINUTES)
    count = UsageEvent.objects.filter(user=user, created_at__gte=cutoff, success=True).count()
    return count < RATE_LIMIT_MAX_REQUESTS


def check_daily_limit(user, event_type: str, profile=None) -> Tuple[bool, Optional[str]]:
    """(allowed, reason). A separate, complementary check from
    check_rate_limit: that one guards against short bursts (30/minute)
    regardless of daily totals; this one enforces the per-user daily quota
    (chat/image/vision counts and a combined token cap) admins configure on
    UserProfile, reset at local midnight. Returns (True, None) immediately
    for unlimited_usage accounts without running any of the count queries.

    Pass `profile` when the caller already fetched it (e.g. ask_ai, which
    needs it anyway for default_model/memory_enabled) to skip a second,
    redundant UserProfile lookup for the exact same row."""
    if profile is None:
        profile = UserProfile.get_or_create_for(user)
    if profile.unlimited_usage:
        return True, None

    today = timezone.localdate()
    todays_events = UsageEvent.objects.filter(user=user, created_at__date=today, success=True)

    limit_field, label = DAILY_LIMIT_FIELDS.get(event_type, (None, None))
    if limit_field:
        limit = getattr(profile, limit_field)
        used = todays_events.filter(event_type=event_type).count()
        if used >= limit:
            return False, f"Daily limit reached ({limit} {label}/day). Try again tomorrow."

    tokens_used = todays_events.aggregate(
        total=Sum(F('prompt_tokens') + F('completion_tokens'))
    )['total'] or 0
    if tokens_used >= profile.daily_token_limit:
        return False, f"Daily token limit reached ({profile.daily_token_limit:,}/day). Try again tomorrow."

    return True, None
