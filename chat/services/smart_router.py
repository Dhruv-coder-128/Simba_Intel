"""Smart Model Routing (Phase 4) - Intelligent model selection engine
supporting explicit routing modes (AUTO, FAST, BALANCED, POWERFUL, ECONOMICAL)
with reasoning metadata and automatic fallback resolution.
"""
from typing import Tuple
from chat.services.model_registry import MODEL_REGISTRY, list_available_models

AUTO_MODEL_ID = "auto"

ROUTING_MODES = {
    "auto": "Auto (Intelligent Task Routing)",
    "fast": "Fast (Low Latency / Speed)",
    "balanced": "Balanced (Quality & Performance)",
    "powerful": "Powerful (Deep Reasoning & Complex Tasks)",
    "economical": "Economical (Lightweight / Local Resource)",
}

_CODE_KEYWORDS = (
    "def ", "function", "class ", "import ", "const ", "var ", "let ",
    "python", "javascript", "typescript", "html", "css", "sql", "query",
    "algorithm", "bug", "error", "traceback", "exception", "refactor",
    "docker", "kubernetes", "regex", "api", "endpoint", "async", "await",
)

_COMPLEX_KEYWORDS = (
    "explain in detail", "analyze", "analyse", "step by step", "step-by-step",
    "write a", "generate", "design", "architecture", "compare", "pros and cons",
    "summarize", "summarise", "essay", "in depth", "comprehensive", "detailed",
    "critique", "review", "evaluate", "breakdown",
)

_SIMPLE_GREETINGS = (
    "hi", "hello", "hey", "thanks", "thank you", "ok", "okay", "yo", "sup", "good morning", "good evening",
)

OX_ALPHA_MODEL = "ox-alpha"
FAST_MODEL = "nova-mind"
CAPABLE_MODEL = "cyber-max"
VISION_MODEL = "sky-net-mini"
OFFLINE_MODEL = "offline"

_COMPLEX_LENGTH_THRESHOLD = 200
_SIMPLE_WORD_THRESHOLD = 5


def _model_display(mid: str) -> str:
    cfg = MODEL_REGISTRY.get(mid)
    return cfg.display_name if cfg else mid


def _is_model_healthy(mid: str) -> bool:
    if mid not in MODEL_REGISTRY:
        return False
    try:
        from chat.services.ai_router import is_provider_cooling_down
        cfg = MODEL_REGISTRY[mid]
        return not is_provider_cooling_down(cfg.provider)
    except Exception:
        return True


def _pick_healthy_model(candidates: list[str], fallback: str) -> str:
    for c in candidates:
        if c in MODEL_REGISTRY and _is_model_healthy(c):
            return c
    return fallback if fallback in MODEL_REGISTRY else (OX_ALPHA_MODEL if OX_ALPHA_MODEL in MODEL_REGISTRY else list(MODEL_REGISTRY.keys())[0])


def route_with_reason(
    mode_or_model: str,
    user_query: str,
    has_image_attachments: bool,
    default_model_id: str = OX_ALPHA_MODEL
) -> Tuple[str, str, str]:
    """Resolves routing mode or manual model choice into (resolved_model_id, mode_name, reason).

    Returns:
        (model_id, routing_mode, routing_reason)
    """
    mode = (mode_or_model or "auto").strip().lower()

    if has_image_attachments:
        chosen = VISION_MODEL if VISION_MODEL in MODEL_REGISTRY else (default_model_id or OX_ALPHA_MODEL)
        return chosen, "vision", f"Vision Mode: Visual inputs detected; routed to {_model_display(chosen)} vision engine."

    # Manual override (direct model ID specified) - STRICT fidelity to user's choice
    if mode not in ROUTING_MODES:
        if mode in MODEL_REGISTRY:
            return mode, "manual", f"Manual Override: User explicitly selected {_model_display(mode)}."
        # Unknown model ID -> fallback to default
        fallback = default_model_id if default_model_id in MODEL_REGISTRY else OX_ALPHA_MODEL
        return fallback, "manual", f"Fallback: Requested model '{mode}' not active; defaulted to {_model_display(fallback)}."

    query = (user_query or "").strip()
    query_lower = query.lower()

    if mode == "fast":
        target = FAST_MODEL if FAST_MODEL in MODEL_REGISTRY else default_model_id
        return target, "fast", f"Fast Mode: Selected {_model_display(target)} for sub-second latency."

    if mode == "balanced":
        target = CAPABLE_MODEL if CAPABLE_MODEL in MODEL_REGISTRY else default_model_id
        return target, "balanced", f"Balanced Mode: Selected {_model_display(target)} for balanced speed and depth."

    if mode == "powerful":
        target = OX_ALPHA_MODEL if OX_ALPHA_MODEL in MODEL_REGISTRY else default_model_id
        return target, "powerful", f"Powerful Mode: Selected {_model_display(target)} for maximum reasoning capability."

    if mode == "economical":
        target = OFFLINE_MODEL if OFFLINE_MODEL in MODEL_REGISTRY else (FAST_MODEL if FAST_MODEL in MODEL_REGISTRY else default_model_id)
        return target, "economical", f"Economical Mode: Selected {_model_display(target)} for lightweight compute."

    # mode == 'auto' - select best model and check provider health
    target = None
    reason_prefix = "Auto"
    if any(k in query_lower for k in _CODE_KEYWORDS):
        target = OX_ALPHA_MODEL if OX_ALPHA_MODEL in MODEL_REGISTRY else default_model_id
        reason_prefix = "Auto: Code & technical architecture detected"
    elif any(k in query_lower for k in _COMPLEX_KEYWORDS) or len(query) > _COMPLEX_LENGTH_THRESHOLD:
        target = OX_ALPHA_MODEL if OX_ALPHA_MODEL in MODEL_REGISTRY else default_model_id
        reason_prefix = "Auto: Deep analysis or complex task detected"
    else:
        word_count = len(query.split())
        if word_count <= _SIMPLE_WORD_THRESHOLD or query_lower.strip(" !.?") in _SIMPLE_GREETINGS:
            target = FAST_MODEL if FAST_MODEL in MODEL_REGISTRY else default_model_id
            reason_prefix = "Auto: Short greeting or quick query"
        else:
            target = OX_ALPHA_MODEL if OX_ALPHA_MODEL in MODEL_REGISTRY else (default_model_id or CAPABLE_MODEL)
            reason_prefix = "Auto: Standard query"

    # If primary auto target's provider is cooling down, intelligently select a healthy alternative
    if not _is_model_healthy(target):
        healthy_alt = _pick_healthy_model([FAST_MODEL, CAPABLE_MODEL, "quantum-core", "sky-net-mini"], fallback=target)
        if healthy_alt != target:
            return healthy_alt, "auto", f"{reason_prefix}; routed to available core {_model_display(healthy_alt)} (primary provider cooling down)."

    return target, "auto", f"{reason_prefix}; routed to {_model_display(target)}."


def choose_model(user_query: str, has_image_attachments: bool, default_model_id: str) -> str:
    """Backward-compatible helper returning model_id only."""
    model_id, _mode, _reason = route_with_reason("auto", user_query, has_image_attachments, default_model_id)
    return model_id


def resolve_model_id(requested_model_id: str, user_query: str, has_image_attachments: bool, default_model_id: str) -> str:
    """Backward-compatible helper resolving model ID."""
    model_id, _mode, _reason = route_with_reason(requested_model_id, user_query, has_image_attachments, default_model_id)
    return model_id

