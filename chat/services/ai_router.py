
from typing import Generator, Dict, Any
from chat.services.provider_manager import get_provider
from chat.services.model_registry import get_model_config


def chat_stream(
    model_id: str,
    messages: list[Dict[str, Any]],
    **kwargs
) -> Generator[str, None, None]:
    model_config = get_model_config(model_id)
    provider = get_provider(model_config.provider)
    return provider.chat_stream(messages, model_config.actual_model, **kwargs)


def chat(
    model_id: str,
    messages: list[Dict[str, Any]],
    **kwargs
) -> str:
    model_config = get_model_config(model_id)
    provider = get_provider(model_config.provider)
    return provider.chat(messages, model_config.actual_model, **kwargs)


def vision(
    model_id: str,
    messages: list[Dict[str, Any]],
    **kwargs
) -> str:
    model_config = get_model_config(model_id)
    provider = get_provider(model_config.provider)
    return provider.vision(messages, model_config.actual_model, **kwargs)


def supports_real_usage(model_id: str) -> bool:
    """True if this model's provider can report real token usage (currently
    only Mistral, verified against its OpenAI-compatible stream_options
    support) - everything else falls back to a text-length estimate."""
    model_config = get_model_config(model_id)
    return model_config.provider == "mistral"
