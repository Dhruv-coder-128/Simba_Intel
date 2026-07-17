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
_GENERIC_TITLE_PATTERN = re.compile(r"^(New Chat|Attachment: .+)$")


def maybe_generate_smart_title(session, first_user_query, first_ai_response):
    """Called once, right after a session's very first turn completes.
    Upgrades the naive truncated/generic title (set at session-creation
    time, before any reply existed to title it from) to a real AI-generated
    one. Never touches a title the user has since renamed by hand."""
    if not _GENERIC_TITLE_PATTERN.match(session.title or "") and session.title not in (
        (first_user_query or "")[:30],
    ):
        return
    try:
        prompt = f"User: {first_user_query}\nAssistant: {first_ai_response}"
        title = ai_chat(MEMORY_MODEL_ID, [
            {"role": "system", "content": TITLE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]).strip().strip('"').strip()
        if title:
            session.title = title[:255]
            session.save(update_fields=["title"])
    except Exception as e:
        logger.warning("Smart title generation failed (session=%s): %s", session.id, e)


def suggest_followups(last_assistant_reply: str) -> list:
    """On-demand only (not called automatically after every turn) - an
    extra AI call per message just to offer suggestions nobody may click
    isn't worth the latency/cost on the critical path, so this is exposed
    as its own endpoint the frontend calls lazily instead."""
    if not (last_assistant_reply or "").strip():
        return []
    try:
        result = ai_chat(MEMORY_MODEL_ID, [
            {"role": "system", "content": FOLLOWUP_SYSTEM_PROMPT},
            {"role": "user", "content": last_assistant_reply[:4000]},
        ]).strip()
        suggestions = [line.strip(" -*\t") for line in result.splitlines() if line.strip(" -*\t")]
        return suggestions[:3]
    except Exception as e:
        logger.warning("Follow-up suggestion failed: %s", e)
        return []


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
