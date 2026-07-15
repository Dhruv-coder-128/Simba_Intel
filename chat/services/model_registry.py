
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
