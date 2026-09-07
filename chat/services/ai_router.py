
import logging
from typing import Generator, Dict, Any, Callable, Optional
from chat.services.provider_manager import get_provider
from chat.services.model_registry import get_model_config, get_fallback_chain

logger = logging.getLogger("simba_intel")

SAFETY_INSTRUCTION = """
You must remain respectful and professional regardless of the user's language.
Never retaliate, mirror, imitate, endorse, or unnecessarily repeat profanity, slurs, vulgarity, degrading insults, abusive nicknames, or sexually degrading language directed at any person.
If abusive wording is irrelevant to the user's actual question, ignore it and answer the underlying question normally.
Never attach an insult supplied by the user to a person's name, title, identity, occupation, relationship, or description.
When referring to SIMBA's creator/developer/team or any other person, always use neutral and respectful wording.
Do not become hostile merely because the user is hostile.
""".strip()

def _inject_safety_instruction(messages: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    if not messages:
        return messages
    
    injected_messages = []
    system_found = False
    
    for msg in messages:
        if not system_found and msg.get("role") == "system":
            new_msg = dict(msg)
            new_msg["content"] = f"{new_msg.get('content', '')}\n\n{SAFETY_INSTRUCTION}"
            injected_messages.append(new_msg)
            system_found = True
        else:
            injected_messages.append(dict(msg))
            
    if not system_found:
        injected_messages.insert(0, {"role": "system", "content": SAFETY_INSTRUCTION})
        
    return injected_messages


import re
import time

def is_rate_limit_error(exc: Exception) -> bool:
    """True if exception indicates an upstream AI provider HTTP 429 / rate limit / quota exhaustion."""
    if not exc:
        return False
    exc_type = type(exc).__name__
    if exc_type in ("RateLimitError", "TooManyRequestsError", "QuotaExceededError"):
        return True
    if getattr(exc, "status_code", None) == 429:
        return True
    response = getattr(exc, "response", None)
    if response and getattr(response, "status_code", None) == 429:
        return True
    text = str(exc).lower()
    return any(kw in text for kw in ("rate limit", "rate_limit", "429", "too many requests", "quota exceeded", "resource has been exhausted", "tpm limit", "rpm limit"))


def extract_retry_after(exc: Exception) -> Optional[int]:
    """Extract numeric retry-after seconds from provider exception if present."""
    if not exc:
        return None
    retry_after = getattr(exc, "retry_after", None)
    if isinstance(retry_after, (int, float)) and retry_after > 0:
        return int(retry_after)
    response = getattr(exc, "response", None)
    if response and hasattr(response, "headers"):
        header_val = response.headers.get("retry-after") or response.headers.get("Retry-After")
        if header_val:
            try:
                return max(1, int(float(header_val)))
            except (ValueError, TypeError):
                pass
    text = str(exc)
    match = re.search(r"(?:retry\s+after|try\s+again\s+in)\s+([0-9]+(?:\.[0-9]+)?)\s*(?:s|sec|seconds)?", text, re.IGNORECASE)
    if match:
        try:
            return max(1, int(float(match.group(1))))
        except (ValueError, TypeError):
            pass
    return None


from django.core.cache import cache

_PROVIDER_COOLDOWN_PREFIX = "provider_cooldown"
DEFAULT_COOLDOWN_SECONDS = 60


def is_provider_cooling_down(provider: str) -> bool:
    """True if the given provider is currently in a temporary 429 rate-limit cooldown."""
    if not provider:
        return False
    return cache.get(f"{_PROVIDER_COOLDOWN_PREFIX}:{provider.lower()}") is not None


def mark_provider_cooldown(provider: str, seconds: int = DEFAULT_COOLDOWN_SECONDS) -> None:
    """Sets a temporary cooldown on an exhausted or rate-limited provider."""
    if not provider:
        return
    timeout = max(5, seconds) if seconds else DEFAULT_COOLDOWN_SECONDS
    cache.set(f"{_PROVIDER_COOLDOWN_PREFIX}:{provider.lower()}", True, timeout=timeout)


def clear_provider_cooldown(provider: str) -> None:
    """Clears cooldown for a provider."""
    if not provider:
        return
    cache.delete(f"{_PROVIDER_COOLDOWN_PREFIX}:{provider.lower()}")


def chat_stream(
    model_id: str,
    messages: list[Dict[str, Any]],
    **kwargs
) -> Generator[str, None, None]:
    model_config = get_model_config(model_id)
    provider = get_provider(model_config.provider)
    safe_messages = _inject_safety_instruction(messages)
    return provider.chat_stream(safe_messages, model_config.actual_model, **kwargs)


def is_non_retryable_error(exc: Exception) -> bool:
    """True for errors where immediate retries are guaranteed to fail and only waste tokens/quota."""
    if not exc:
        return False
    status = getattr(exc, "status_code", None) or getattr(exc, "raw_status_code", None)
    if status in (400, 401, 403, 404, 429):
        return True
    exc_type = type(exc).__name__
    if exc_type in ("RateLimitError", "AuthenticationError", "PermissionDeniedError", "NotFoundError", "BadRequestError"):
        return True
    text = str(exc).lower()
    return any(kw in text for kw in (
        "rate limit", "rate_limit", "429", "quota", "unauthorized", "401",
        "forbidden", "403", "404", "model not found", "tier_not_allowed",
        "invalid model", "does not exist", "context_length_exceeded"
    ))


def chat_stream_with_failover(
    model_id: str,
    messages: list[Dict[str, Any]],
    on_switch: Optional[Callable[[str], None]] = None,
    retries_per_model: int = 2,
    allow_fallback: bool = True,
    **kwargs
) -> Generator[str, None, None]:
    """Tries the requested model and safe fallback chain without duplicate requests or retry storms.

    - Rate limit (429), Auth (401/403), Not Found (404), Bad Request (400): 0 retries.
    - Transient errors (5xx/overloaded/timeout): at most 1 controlled retry with brief backoff.
    - Failover occurs only before any tokens are yielded to client.
    """
    candidates = [model_id]
    if allow_fallback:
        candidates.extend(get_fallback_chain(model_id))
    
    last_error: Optional[Exception] = None
    safe_messages = _inject_safety_instruction(messages)

    for candidate in candidates:
        model_config = get_model_config(candidate)
        provider_name = model_config.provider

        # In fallback mode, skip candidates whose provider is currently known to be cooling down
        if allow_fallback and candidate != model_id and is_provider_cooling_down(provider_name):
            continue

        provider = get_provider(provider_name)

        # Allow at most 1 retry (2 attempts) for transient errors; non-retryable errors exit immediately
        max_attempts = max(1, retries_per_model)
        for attempt in range(max_attempts):
            try:
                gen = provider.chat_stream(safe_messages, model_config.actual_model, **kwargs)
                first_chunk = next(gen)
            except StopIteration:
                # A real, successful call that just produced no tokens
                return
            except Exception as e:
                last_error = e
                is_429 = is_rate_limit_error(e)
                retry_after = extract_retry_after(e)
                if is_429:
                    mark_provider_cooldown(provider_name, retry_after or DEFAULT_COOLDOWN_SECONDS)
                
                non_retryable = is_non_retryable_error(e)
                logger.warning(
                    "chat_stream %s (provider=%s, model=%s, attempt=%d/%d): %s",
                    "rate-limited" if is_429 else "failed",
                    provider_name, candidate, attempt + 1, max_attempts, e,
                )
                
                # Never retry non-retryable errors (429, 401, 403, 404, 400)
                if non_retryable or attempt + 1 >= max_attempts:
                    break
                
                time.sleep(0.4)
                continue

            if candidate != model_id and on_switch:
                on_switch(candidate)
            yield first_chunk
            yield from gen
            return

    raise last_error


def chat(
    model_id: str,
    messages: list[Dict[str, Any]],
    **kwargs
) -> str:
    model_config = get_model_config(model_id)
    provider = get_provider(model_config.provider)
    safe_messages = _inject_safety_instruction(messages)
    return provider.chat(safe_messages, model_config.actual_model, **kwargs)


def vision(
    model_id: str,
    messages: list[Dict[str, Any]],
    **kwargs
) -> str:
    model_config = get_model_config(model_id)
    provider = get_provider(model_config.provider)
    safe_messages = _inject_safety_instruction(messages)
    return provider.vision(safe_messages, model_config.actual_model, **kwargs)


def supports_real_usage(model_id: str) -> bool:
    """True if this model's provider can report real token usage (Mistral and
    OpenRouter via OpenAI-compatible stream_options support) - everything else
    falls back to a text-length estimate."""
    model_config = get_model_config(model_id)
    return model_config.provider in ("mistral", "openrouter")
