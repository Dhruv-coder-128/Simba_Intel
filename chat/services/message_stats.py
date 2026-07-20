
import time
import uuid
from typing import Optional

from django.utils import timezone

from chat.services.model_registry import get_model_config

_encoding = None


def _get_encoding():
    """Lazy singleton, one load per worker process (~4s cold, instant after)
    - a tiktoken BPE encoding is the closest widely-available tokenizer to
    every hosted model here (NVIDIA/Groq/Mistral don't publish/pip-ship
    their own), used as the silent fallback counter below when a provider
    doesn't report real usage."""
    global _encoding
    if _encoding is None:
        import tiktoken
        _encoding = tiktoken.get_encoding("cl100k_base")
    return _encoding


def _count_tokens(text: str) -> int:
    if not text:
        return 0
    return len(_get_encoding().encode(text))


def build_stats(
    *,
    model_id: str,
    serving_model_id: str,
    resolved: Optional[dict] = None,
    captured_usage: Optional[dict] = None,
    prompt_text: str = "",
    completion_text: str = "",
    start_time: float,
    first_token_time: Optional[float] = None,
    end_time: Optional[float] = None,
    streaming: bool = True,
    is_vision: bool = False,
    is_image_gen: bool = False,
    memory_used: bool = False,
) -> dict:
    """Assembles the metadata for one AI response, stored in Message.
    extra_data['stats'] and returned as-is by the /messages/<id>/info/
    endpoint (chat/views.py's message_info). Every field is always a real
    number/value - see chat/providers/*_provider.py's on_usage (real token
    counts, Mistral only today) and on_model_resolved (real underlying
    model, virtual/nvidia pools only) for the officially-reported path;
    when a provider doesn't report usage, token counts are computed here
    with a real tokenizer (_count_tokens) rather than left blank.

    `model_id` is the model the user actually requested; `serving_model_id`
    is what chat_stream_with_failover's on_switch reported (only differs on
    a cross-model FALLBACK_CHAINS switch, e.g. cyber-max -> nova-mind).
    `resolved` is _stream_with_failover's on_model_resolved dict - only
    populated for virtual/nvidia pooled providers, which don't expose their
    real underlying model any other way.
    """
    resolved = resolved or {}
    captured_usage = captured_usage or {}
    end_time = end_time if end_time is not None else time.time()
    serving_config = get_model_config(serving_model_id)
    fallback_used = serving_model_id != model_id

    prompt_tokens = captured_usage.get("prompt_tokens")
    if prompt_tokens is None:
        prompt_tokens = _count_tokens(prompt_text)
    completion_tokens = captured_usage.get("completion_tokens")
    if completion_tokens is None:
        completion_tokens = _count_tokens(completion_text)
    total_tokens = prompt_tokens + completion_tokens

    actual_model = resolved.get("model") or serving_config.actual_model

    # Non-streaming calls (vision, image gen) never set first_token_time -
    # their entire reply arrives as one unit, so time-to-first-token really
    # is the same instant as the full response time, not a missing value.
    if first_token_time is None:
        first_token_time = end_time

    return {
        "provider": serving_config.display_name,
        "actual_model": actual_model,
        "input_tokens": prompt_tokens,
        "output_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "response_time_s": round(end_time - start_time, 2),
        "ttft_s": round(first_token_time - start_time, 2),
        "streaming": streaming,
        "is_vision": is_vision,
        "is_image_gen": is_image_gen,
        "fallback_used": fallback_used,
        "fallback_model": serving_config.display_name,
        "memory_used": memory_used,
        "timestamp": timezone.now().isoformat(),
        "request_id": f"req_{uuid.uuid4().hex}",
        "context_window_used": None,
    }
