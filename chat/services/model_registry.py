
from dataclasses import dataclass
from typing import Dict


@dataclass
class ModelConfig:
    display_name: str
    provider: str
    actual_model: str
    supports_vision: bool = False
    supports_image_gen: bool = False
    # Role-gated model access (AI Control Center) - "user" (chat/models.py's
    # Role.USER) means open to everyone, which is every model's default
    # today, so this changes nothing unless a future model is registered
    # with a higher minimum. MODEL_REGISTRY is a static, code-defined dict,
    # not a database table - so this is a real, enforced mechanism (see
    # chat/views.py's ask_ai, where it's checked), but not yet something an
    # admin can change without a deploy. Moving MODEL_REGISTRY into the
    # database is the natural next step if per-model role requirements need
    # to become runtime-editable.
    min_role: str = "user"


MODEL_REGISTRY: Dict[str, ModelConfig] = {
    "cyber-max": ModelConfig(
        display_name="Cyber Max",
        # "virtual" = routed through chat/providers/virtual_provider.py's
        # VirtualRouterProvider rather than calling a single real model
        # directly - actual_model below isn't a real Groq model id, it's the
        # pool key VirtualRouterProvider looks up in MODEL_POOLS. Cyber Max
        # itself still appears as exactly one model everywhere else in the
        # app (chat list, analytics, etc.) - only this ModelConfig and
        # MODEL_POOLS know it's backed by more than one real model.
        provider="virtual",
        actual_model="cyber-max-pool"
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


# Provider failover (Part 4) - ordered list of standby models tried, in
# order, if the requested model's own provider call fails. Chosen to cross
# providers wherever a same-capability standby exists on the other one (text
# models fail over groq<->mistral), so a whole-provider outage doesn't take
# the feature down with it - vision only has one integrated provider
# (Mistral) today, so its chain can only fail over to another Mistral model,
# which still isolates a single-model/endpoint problem even though it can't
# survive a Mistral-wide outage. image-studio has no chain: Pollinations is
# the only image provider integrated, so there's nothing to fail over to.
FALLBACK_CHAINS: Dict[str, list] = {
    "cyber-max": ["nova-mind", "sky-net-mini"],
    "nova-mind": ["cyber-max", "sky-net-mini"],
    "sky-net": ["sky-net-mini"],
    "sky-net-pro": ["sky-net-mini"],
    "sky-net-mini": ["sky-net"],
}


def get_fallback_chain(model_id: str) -> list:
    return FALLBACK_CHAINS.get(model_id.lower(), [])


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
            "min_role": config.min_role,
        }
        for mid, config in MODEL_REGISTRY.items()
    ]


def is_model_allowed_for_user(model_id: str, user) -> bool:
    """The one enforcement point for ModelConfig.min_role - called from
    chat/views.py's ask_ai right after resolving the requested model, so a
    request for a role-gated model a user isn't entitled to fails before
    any provider call is made."""
    from chat.permissions import has_role_at_least

    config = MODEL_REGISTRY.get(model_id.lower())
    if config is None:
        return False
    return has_role_at_least(user, config.min_role)
