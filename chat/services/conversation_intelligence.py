"""Conversation Intelligence (Part 6) - AI-generated titles, on-demand
follow-up suggestions, and a lightweight "related conversations" heuristic.

Kept separate from conversation_memory.py on purpose: that module is about
*remembering* (summarizing/compressing/recalling), this one is about
*presenting* a conversation back to the user more usefully. They share the
same "best-effort, never break the caller" posture, and the same cheap
model (chat.services.conversation_memory.MEMORY_MODEL_ID) for the same
reason - short outputs from a short prompt, where the flagship model's
extra quality isn't worth its latency/cost.
"""
import logging
import re

from chat.services.ai_router import chat as ai_chat
from chat.services.conversation_memory import MEMORY_MODEL_ID
from chat.services.model_registry import get_fallback_chain

logger = logging.getLogger("simba_intel")

TITLE_SYSTEM_PROMPT = (
    "Generate a short, specific title (3-6 words, no quotes, no trailing "
    "punctuation) for a conversation that starts with the exchange below. "
    "Respond with the title only."
)

FOLLOWUP_SYSTEM_PROMPT = (
    "Suggest exactly 3 short follow-up questions or requests the user might "
    "naturally ask next, based on the reply below. One per line, no "
    "numbering, no quotes, each under 12 words."
)

# Generic titles the naive truncation fallback can produce - only these get
# upgraded, so a user who already renamed a chat by hand never has their
# choice silently overwritten.
_GENERIC_TITLE_PATTERN = re.compile(r"^(New Chat|Chat|Untitled|New Conversation|Attachment: .+)$", re.IGNORECASE)

_MARKDOWN_NOISE_RE = re.compile(r"```.*?```", re.DOTALL)
_MARKDOWN_CHARS_RE = re.compile(r"[`*_#>]")

_FILLER_PREFIXES_RE = re.compile(
    r"^(can you please|could you please|please|can you|could you|help me with|how do i|how to|what is|tell me about|explain|write a|create a|generate a)\s+",
    re.IGNORECASE
)

_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "to", "of", "in", "on", "for",
    "and", "or", "with", "how", "what", "why", "do", "does", "can", "i", "my",
    "me", "you", "your", "it", "this", "that", "please", "help", "about",
}


def _deterministic_title_fallback(user_query: str) -> str:
    """Deterministic, high-quality title fallback for when AI generation fails.
    Strips polite filler, selects first 3-6 substantive words, and Title Cases."""
    clean = _MARKDOWN_NOISE_RE.sub(" ", user_query or "")
    clean = _MARKDOWN_CHARS_RE.sub(" ", clean)
    clean = _FILLER_PREFIXES_RE.sub("", clean.strip()).strip()
    words = [w.strip(" ,.-;:_!?\"'()") for w in clean.split() if w.strip(" ,.-;:_!?\"'()")]
    
    if not words:
        return "Intelligence Workspace Session"
    
    substantive = [w for w in words if w.lower() not in _STOPWORDS]
    selected = substantive[:5] if len(substantive) >= 2 else words[:5]
    
    title = " ".join(selected).title()
    return title[:60] if title else "AI Workspace Session"


def maybe_generate_smart_title(session, first_user_query, first_ai_response):
    """Sets a clean, substantive title for the session's first turn using high-quality
    deterministic synthesis. Never touches a user-renamed title."""
    current_title = (session.title or "").strip()
    is_generic = _GENERIC_TITLE_PATTERN.match(current_title) or not current_title or current_title == (first_user_query or "")[:30]
    
    if not is_generic:
        return

    fallback_title = _deterministic_title_fallback(first_user_query)
    session.title = fallback_title
    session.save(update_fields=["title"])


def _dedupe_suggestions(raw: str) -> list:
    suggestions = [line.strip(" -*\t123456789.") for line in raw.splitlines() if line.strip(" -*\t123456789.")]
    seen = set()
    deduped = []
    for s in suggestions:
        key = s.lower()
        if key in seen or len(s) < 5:
            continue
        seen.add(key)
        deduped.append(s)
    return deduped[:4]


def _derive_followups_from_reply(reply: str) -> list:
    """Context-aware fallback when AI follow-up generation is unavailable.
    Inspects reply content structure (code vs analysis vs general prose)."""
    text = (reply or "").strip()
    if not text:
        return [
            "Explain this further",
            "Give a concrete example",
            "What are the next steps?"
        ]

    has_code = "```" in text or any(k in text.lower() for k in ("def ", "class ", "function", "import ", "const "))
    has_steps = any(marker in text for marker in ("1.", "2.", "Step 1", "Phase 1", "- [ ]"))
    is_long = len(text) > 600

    suggestions = []
    if has_code:
        suggestions.append("Run code review & identify edge cases")
        suggestions.append("Generate automated test cases")
        suggestions.append("Explain line-by-line implementation")
    elif has_steps:
        suggestions.append("Walk through the next implementation step")
        suggestions.append("What potential bottlenecks should we watch for?")
        suggestions.append("Summarize key prerequisites")
    elif is_long:
        suggestions.append("Summarize the key takeaways and decisions")
        suggestions.append("Extract actionable next steps")
        suggestions.append("Compare alternative trade-offs")
    else:
        suggestions.append("Can you elaborate on this?")
        suggestions.append("Provide a practical real-world example")
        suggestions.append("What are the core advantages and limitations?")

    return suggestions[:3]


def suggest_followups(last_assistant_reply: str) -> list:
    """Fast, context-aware, deterministic follow-up generation that makes 0 AI calls."""
    if not (last_assistant_reply or "").strip():
        return []
    return _derive_followups_from_reply(last_assistant_reply)


_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "to", "of", "in", "on", "for",
    "and", "or", "with", "how", "what", "why", "do", "does", "can", "i", "my",
    "me", "you", "your", "it", "this", "that", "please", "help", "about",
}


def _significant_words(text: str) -> set:
    words = re.findall(r"[a-zA-Z']{3,}", (text or "").lower())
    return {w for w in words if w not in _STOPWORDS}


def find_related_conversations(session, limit=5):
    """Deliberately not embeddings/vector-search based - there's no vector
    store in this project, and adding one just for this would be a lot of
    new infrastructure for a "related chats" list. Word-overlap between
    session titles is a cheap, dependency-free proxy that's good enough for
    surfacing a handful of plausibly-related past conversations."""
    from chat.models import ChatSession

    my_words = _significant_words(session.title)
    if not my_words:
        return []

    candidates = ChatSession.objects.filter(
        user=session.user, is_archived=False,
    ).exclude(id=session.id).only("id", "title")

    scored = []
    for candidate in candidates:
        overlap = my_words & _significant_words(candidate.title)
        if overlap:
            scored.append((len(overlap), candidate))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [c for _, c in scored[:limit]]
