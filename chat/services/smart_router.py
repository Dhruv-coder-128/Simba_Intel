"""Smart Model Routing (Part 3) - a heuristic engine that picks a concrete
model when the user (or the composer's default) is "auto" instead of a real
model_id. Deliberately rule-based, not ML-based: there's no training data,
labeling pipeline, or inference infra in this project to justify one, and a
transparent set of rules is easier to reason about, tune, and explain to a
user ("why did it pick this model?") than a black-box classifier would be.
Manual override always wins - this is only ever consulted when the request
explicitly asks for "auto".
"""
from chat.services.model_registry import MODEL_REGISTRY

AUTO_MODEL_ID = "auto"

# Simple, honest heuristics over the four real chat/vision models actually
# registered - kept as short, named buckets rather than one big scoring
# function so each rule's intent stays obvious at a glance.
_COMPLEX_KEYWORDS = (
    "explain in detail", "analyze", "analyse", "step by step", "step-by-step",
    "write a", "generate", "design", "architecture", "compare", "pros and cons",
    "summarize", "summarise", "essay", "in depth", "comprehensive", "detailed",
)
_SIMPLE_GREETINGS = (
    "hi", "hello", "hey", "thanks", "thank you", "ok", "okay", "yo", "sup",
)

OX_ALPHA_MODEL = "ox-alpha"
FAST_MODEL = "nova-mind"
CAPABLE_MODEL = "cyber-max"
VISION_MODEL = "sky-net-mini"

# Long enough to look like a real request for depth, short enough that most
# ordinary questions still land in the "normal" (default_model) bucket.
_COMPLEX_LENGTH_THRESHOLD = 220
_SIMPLE_WORD_THRESHOLD = 4


def choose_model(user_query: str, has_image_attachments: bool, default_model_id: str) -> str:
    """Resolves "auto" to one real, registered model_id. Ox Alpha has FIRST priority
    as the primary intelligence/decision-making model.
    """
    if has_image_attachments:
        return VISION_MODEL if VISION_MODEL in MODEL_REGISTRY else (default_model_id or OX_ALPHA_MODEL)

    # 1. Ox Alpha is ALWAYS first priority for Auto (Smart Routing)
    if OX_ALPHA_MODEL in MODEL_REGISTRY:
        return OX_ALPHA_MODEL

    # 2. User's configured default model if registered
    if default_model_id in MODEL_REGISTRY:
        return default_model_id

    query = (user_query or "").strip()
    query_lower = query.lower()

    if any(keyword in query_lower for keyword in _COMPLEX_KEYWORDS) or len(query) > _COMPLEX_LENGTH_THRESHOLD:
        return CAPABLE_MODEL if CAPABLE_MODEL in MODEL_REGISTRY else default_model_id

    word_count = len(query.split())
    if word_count <= _SIMPLE_WORD_THRESHOLD or query_lower.strip(" !.?") in _SIMPLE_GREETINGS:
        return FAST_MODEL if FAST_MODEL in MODEL_REGISTRY else default_model_id

    return CAPABLE_MODEL


def resolve_model_id(requested_model_id: str, user_query: str, has_image_attachments: bool, default_model_id: str) -> str:
    """The one call site every view needs: pass through anything that isn't
    literally "auto" unchanged (manual override), otherwise route."""
    if (requested_model_id or "").lower() != AUTO_MODEL_ID:
        return requested_model_id
    return choose_model(user_query, has_image_attachments, default_model_id)
