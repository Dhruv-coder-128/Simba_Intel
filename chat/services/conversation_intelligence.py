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


def _dedupe_suggestions(raw: str) -> list:
    suggestions = [line.strip(" -*\t") for line in raw.splitlines() if line.strip(" -*\t")]
    # The prompt asks for 3 distinct questions, but nothing enforces that
    # server-side - dedupe case-insensitively (keeping first-seen casing
    # and order) so a model that repeats itself never surfaces the same
    # suggestion twice.
    seen = set()
    deduped = []
    for s in suggestions:
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(s)
    return deduped[:3]


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_MARKDOWN_NOISE_RE = re.compile(r"```.*?```", re.DOTALL)
_MARKDOWN_CHARS_RE = re.compile(r"[`*_#>]")

_FALLBACK_TEMPLATES = [
    "Can you explain more about: {0}",
    "Give me an example related to: {0}",
    "What are the key details about: {0}",
]


def _derive_followups_from_reply(reply: str) -> list:
    """Last-resort, non-AI fallback for when every AI attempt in
    suggest_followups fails (e.g. a full provider outage, or the shared
    Groq quota below being exhausted for every candidate model at once).
    Always derived from the ACTUAL reply text - never a static/generic
    list - so a user is never shown suggestions unrelated to what Simba
    just said. Guarantees exactly 3 whenever `reply` has any real content:
    picks up to 3 distinct sentences from the reply and wraps each in a
    natural follow-up prompt, padding by reusing sentences (still real
    content, just repeated) if the reply is too short to have 3 distinct
    ones."""
    text = _MARKDOWN_NOISE_RE.sub(" ", reply or "")
    text = _MARKDOWN_CHARS_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []

    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if len(s.strip()) > 8]
    if not sentences:
        sentences = [text]

    pool = []
    seen = set()
    for s in sentences:
        key = s.lower()
        if key not in seen:
            seen.add(key)
            pool.append(s)
    while len(pool) < 3:
        pool.append(sentences[len(pool) % len(sentences)])

    suggestions = []
    for i in range(3):
        snippet = pool[i]
        if len(snippet) > 60:
            snippet = snippet[:57].rstrip() + "..."
        suggestions.append(_FALLBACK_TEMPLATES[i].format(snippet))
    return suggestions


def suggest_followups(last_assistant_reply: str) -> list:
    """On-demand only (not called automatically after every turn) - an
    extra AI call per message just to offer suggestions nobody may click
    isn't worth the latency/cost on the critical path, so this is exposed
    as its own endpoint the frontend calls lazily instead.

    Retries once, against the next model in MEMORY_MODEL_ID's own failover
    chain, before falling back further. This isn't a generic robustness
    nicety: MEMORY_MODEL_ID and the default chat model both resolve to the
    same Groq API key, which shares one daily token quota with ordinary
    chat traffic - a conversation that has already sent several turns can
    exhaust that quota mid-session, so a same-model retry would just fail
    again immediately. Retrying against the next candidate (a different
    provider) is what actually gives a second real chance to succeed.

    If BOTH attempts genuinely fail (or return nothing usable), this still
    never returns an empty list as long as there's a real reply to work
    from - _derive_followups_from_reply deterministically builds 3
    suggestions straight from that reply's own text, so the feature never
    goes silent even during a full AI-provider outage, without ever
    inventing generic, conversation-unrelated suggestions."""
    if not (last_assistant_reply or "").strip():
        return []
    messages = [
        {"role": "system", "content": FOLLOWUP_SYSTEM_PROMPT},
        {"role": "user", "content": last_assistant_reply[:4000]},
    ]
    candidates = [MEMORY_MODEL_ID] + get_fallback_chain(MEMORY_MODEL_ID)
    for candidate in candidates[:2]:
        try:
            result = ai_chat(candidate, messages).strip()
        except Exception as e:
            logger.warning("Follow-up suggestion failed (model=%s): %s", candidate, e)
            continue
        suggestions = _dedupe_suggestions(result)
        if suggestions:
            return suggestions
    logger.warning("Follow-up suggestion AI generation failed for every candidate - falling back to reply-derived suggestions.")
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
