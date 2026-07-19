
from typing import Dict, Type
from chat.providers.base import BaseProvider
from chat.utils.env import get_env_var


PROVIDER_REGISTRY: Dict[str, str] = {
    "groq": "chat.providers.groq_provider.GroqProvider",
    "mistral": "chat.providers.mistral_provider.MistralProvider",
    # "⚛ Quantum Core" - a fixed-priority NVIDIA text model chain with
    # immediate, no-retry failover (see chat/providers/nvidia_text_provider.py).
    # Its vision() method delegates to chat/providers/nvidia_vision_provider.py's
    # own fixed vision-model chain.
    "nvidia": "chat.providers.nvidia_text_provider.NvidiaTextProvider",
    # Not a real API - routes to whichever of these it wraps (see
    # chat/providers/virtual_provider.py). Dispatched exactly like any other
    # provider here, which is what lets a visible model (e.g. "Cyber Max")
    # be backed by a pool of real models with no special-casing anywhere
    # else in the codebase.
    "virtual": "chat.providers.virtual_provider.VirtualRouterProvider",
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
