
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


def chat_stream(
    model_id: str,
    messages: list[Dict[str, Any]],
    **kwargs
) -> Generator[str, None, None]:
    model_config = get_model_config(model_id)
    provider = get_provider(model_config.provider)
    safe_messages = _inject_safety_instruction(messages)
    return provider.chat_stream(safe_messages, model_config.actual_model, **kwargs)


def chat_stream_with_failover(
    model_id: str,
    messages: list[Dict[str, Any]],
    on_switch: Optional[Callable[[str], None]] = None,
    retries_per_model: int = 2,
    **kwargs
) -> Generator[str, None, None]:
    """Same contract as chat_stream, but tries each model in the requested
    model's fallback chain (see model_registry.FALLBACK_CHAINS) before
    giving up - retries_per_model attempts per candidate first, since a
    transient blip on the user's own chosen model shouldn't force a switch
    away from it.

    Failover can only ever happen before the first token of a candidate is
    yielded: once real output has started reaching the caller, switching
    mid-stream would interleave/duplicate text, so a failure after that
    point propagates as a normal exception instead (existing callers already
    catch and surface it as an inline error message).

    `on_switch(model_id)` fires exactly once, only if the model that ends up
    serving the request isn't the one originally requested - callers use it
    to show a transient "switched providers" notice without persisting it
    into the saved message content.

    `on_model_resolved` isn't a parameter of this function - it flows through
    **kwargs straight into `provider.chat_stream(...)` exactly like `on_usage`
    does. Only virtual/nvidia (pooled) providers ever call it, to report the
    real underlying model they picked; other providers accept it for
    interface parity and never call it, since their caller already knows the
    real model (it's just `model_config.actual_model`).
    """
    candidates = [model_id] + get_fallback_chain(model_id)
    last_error: Optional[Exception] = None
    safe_messages = _inject_safety_instruction(messages)

    for candidate in candidates:
        model_config = get_model_config(candidate)
        provider = get_provider(model_config.provider)

        for attempt in range(retries_per_model):
            try:
                gen = provider.chat_stream(safe_messages, model_config.actual_model, **kwargs)
                first_chunk = next(gen)
            except StopIteration:
                # A real, successful call that just produced no tokens - not
                # a failure, so this must not trigger failover.
                return
            except Exception as e:
                last_error = e
                logger.warning(
                    "chat_stream failed (model=%s, attempt=%d/%d): %s",
                    candidate, attempt + 1, retries_per_model, e,
                )
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
    """True if this model's provider can report real token usage (currently
    only Mistral, verified against its OpenAI-compatible stream_options
    support) - everything else falls back to a text-length estimate."""
    model_config = get_model_config(model_id)
    return model_config.provider == "mistral"
