
from typing import Dict, Type
from chat.providers.base import BaseProvider
from chat.utils.env import get_env_var


PROVIDER_REGISTRY: Dict[str, str] = {
    "groq": "chat.providers.groq_provider.GroqProvider",
    "mistral": "chat.providers.mistral_provider.MistralProvider"
}


_provider_instances: Dict[str, BaseProvider] = {}


def _get_provider_class(provider_name: str) -> Type[BaseProvider]:
    import importlib
    module_path, class_name = PROVIDER_REGISTRY[provider_name].rsplit('.', 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def get_provider(provider_name: str, api_key: str = None, api_base: str = None) -> BaseProvider:
    if provider_name not in _provider_instances:
        provider_class = _get_provider_class(provider_name)
        if not api_key:
            api_key = get_env_var(f"{provider_name.upper()}_API_KEY")
        _provider_instances[provider_name] = provider_class(api_key=api_key, api_base=api_base)
    return _provider_instances[provider_name]
