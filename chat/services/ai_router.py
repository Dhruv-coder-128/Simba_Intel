
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
