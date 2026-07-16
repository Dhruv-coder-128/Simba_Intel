
from dataclasses import dataclass
from typing import Dict


@dataclass
class ModelConfig:
    display_name: str
    provider: str
    actual_model: str
    supports_vision: bool = False
    supports_image_gen: bool = False


MODEL_REGISTRY: Dict[str, ModelConfig] = {
    "cyber-max": ModelConfig(
        display_name="Cyber Max",
        provider="groq",
        actual_model="llama-3.3-70b-versatile"
    ),
    "nova-mind": ModelConfig(
        display_name="Nova Mind",
        provider="groq",
        actual_model="groq/compound-mini"
    ),
    "sky-net": ModelConfig(
        display_name="SkyNet(vision)",
        provider="mistral",
        actual_model="mistral-large-latest",
        supports_vision=True
    ),
    "sky-net-pro": ModelConfig(
        display_name="SkyNet Pro",
        provider="mistral",
        actual_model="mistral-large-latest",
        supports_vision=True
    ),
    "sky-net-mini": ModelConfig(
        display_name="SkyNet Mini",
        provider="mistral",
        actual_model="mistral-medium-3-5",
        supports_vision=True
    ),
    "image-studio": ModelConfig(
        display_name="Image Studio (Image)",
        provider="pollinations",
        actual_model="flux",
        supports_image_gen=True
    )
}


# Provider identity (groq/mistral/pollinations) must never reach a
# customer-facing page - only the admin console is "internal" enough to see
# it raw (chat/admin_views.py deliberately keeps the real provider strings).
# Any user-facing view that groups/displays by provider (chat/views.py's
# analytics_dashboard) should map through this first.
PROVIDER_DISPLAY_NAMES: Dict[str, str] = {
    "groq": "SkyNet Cloud",
    "mistral": "NovaMind Cloud",
    "pollinations": "Image Studio Engine",
    "openai": "Cyber Max Cloud",
}


def provider_display_name(provider: str) -> str:
    return PROVIDER_DISPLAY_NAMES.get(provider, "Simba Cloud")


def get_model_config(model_id: str) -> ModelConfig:
    return MODEL_REGISTRY[model_id.lower()]


def list_available_models() -> list[dict]:
    return [
        {
            "id": mid,
            "display_name": config.display_name,
            "provider": config.provider,
            "supports_vision": config.supports_vision,
            "supports_image_gen": config.supports_image_gen,
        }
        for mid, config in MODEL_REGISTRY.items()
    ]
