"""AI Memory (Part 2) - conversation summarization, long-conversation
compression/context optimization, cross-chat fact extraction, and the read
side that injects both into a fresh request.

Everything here is deliberately best-effort: a summarization or extraction
failure must never break the actual chat turn it's attached to, so every
entry point swallows its own exceptions and logs rather than raising.
"""
import logging

from chat.services.ai_router import chat as ai_chat
from chat.services.memory import messages_to_history_dicts
from chat.services.message_tree import walk_active_chain

logger = logging.getLogger("simba_intel")

# A fast, cheap model for both jobs below - summaries/fact lists are short
# outputs from a (comparatively) short prompt, so the extra quality of the
# heavier chat model isn't worth its latency/cost here.
MEMORY_MODEL_ID = "nova-mind"

# Re-summarize after this many NEW messages have accumulated since the last
# summary - not on every turn, since that would mean one extra AI call per
# message for no real benefit (the summary a few turns stale is still fine
# context for the model).
SUMMARIZE_EVERY_N_MESSAGES = 20

# The most recent N turns are always sent verbatim regardless of summary -
# matches memory.messages_to_history_dicts's own default window.
RECENT_TURNS_KEPT_VERBATIM = 10

SUMMARY_SYSTEM_PROMPT = (
    "You compress conversations into short factual summaries. Respond with "
    "3-5 plain sentences only - no headers, no bullet points, no preamble."
)

FACT_EXTRACTION_PROMPT = (
    "From the conversation below, list up to 3 short, durable facts worth "
    "remembering about the user in future, unrelated conversations - things "
    "like their name, role, ongoing projects, or stated preferences. One "
    "fact per line, no numbering, no extra commentary. If nothing durable "
    "was said, respond with exactly: NONE"
)


def _format_turns(history_dicts):
    lines = []
    for turn in history_dicts:
        speaker = "User" if turn["role"] == "user" else "Assistant"
        lines.append(f"{speaker}: {turn['content']}")
    return "\n".join(lines)


def maybe_summarize_session(session):
    """Call after a turn has been persisted. No-op unless enough new
    messages have accumulated since the last summary to be worth the extra
    AI call. Safe to call on every turn - the threshold check is a single
    cheap count, not a query per candidate."""
    try:
        total_messages = session.thread.count()
        if total_messages - session.summary_message_count < SUMMARIZE_EVERY_N_MESSAGES:
            return

        chain = walk_active_chain(session)
        history = messages_to_history_dicts(chain, limit=len(chain))
        # Leave the most recent window untouched - only what falls before it
        # needs compressing, since that window is always sent verbatim anyway.
        to_summarize = history[:-RECENT_TURNS_KEPT_VERBATIM * 2] if len(history) > RECENT_TURNS_KEPT_VERBATIM * 2 else history
        if not to_summarize:
            return

        turns_text = _format_turns(to_summarize)
        if session.summary:
            user_prompt = (
                f"Existing summary:\n{session.summary}\n\n"
                f"New messages to fold in:\n{turns_text}\n\n"
                "Produce one updated summary covering the existing summary plus the new messages."
            )
        else:
            user_prompt = f"Conversation so far:\n{turns_text}"

        new_summary = ai_chat(MEMORY_MODEL_ID, [
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]).strip()

        if new_summary:
            session.summary = new_summary
            session.summary_message_count = total_messages
            session.save(update_fields=["summary", "summary_message_count"])
    except Exception as e:
        logger.warning("Conversation summarization failed (session=%s): %s", session.id, e)


def build_context_messages(session, user_query, system_prompt, limit=RECENT_TURNS_KEPT_VERBATIM):
    """Replaces the old get_conversation_history + build_messages combo for
    the main send flow - same shape (a plain list of role/content dicts
    ending with the new user turn), but injects the session's summary as an
    extra system message when there's history older than the verbatim
    window, instead of just silently truncating it."""
    chain = walk_active_chain(session)
    history = messages_to_history_dicts(chain, limit=limit)

    messages = [{"role": "system", "content": system_prompt}]
    if session.summary and len(chain) > limit * 2:
        messages.append({
            "role": "system",
            "content": f"Summary of earlier parts of this conversation (for context only): {session.summary}",
        })
    messages.extend(history)
    messages.append({"role": "user", "content": user_query})
    return messages


def extract_and_store_facts(user, session):
    """Cross-chat memory writer - only ever called when the caller has
    already checked UserProfile.memory_enabled. One-shot per session
    (session.facts_extracted), not repeated on every turn."""
    from chat.models import UserFact

    if session.facts_extracted:
        return
    try:
        chain = walk_active_chain(session)
        # Needs a few real turns of substance before extraction is worth
        # running at all - a two-message conversation has nothing durable
        # to find yet.
        if len(chain) < 4:
            return

        history = messages_to_history_dicts(chain, limit=len(chain))
        turns_text = _format_turns(history)
        result = ai_chat(MEMORY_MODEL_ID, [
            {"role": "system", "content": FACT_EXTRACTION_PROMPT},
            {"role": "user", "content": turns_text},
        ]).strip()

        session.facts_extracted = True
        session.save(update_fields=["facts_extracted"])

        if not result or result.strip().upper() == "NONE":
            return

        existing = set(UserFact.objects.filter(user=user).values_list("fact", flat=True))
        for line in result.splitlines():
            fact = line.strip(" -*\t")
            if not fact or fact.upper() == "NONE" or fact in existing:
                continue
            UserFact.objects.create(user=user, fact=fact[:500], source_session=session)
            existing.add(fact)
    except Exception as e:
        logger.warning("Fact extraction failed (session=%s): %s", session.id, e)


def get_user_memory_context(user, limit=10):
    """Read side of cross-chat memory - only called when
    UserProfile.memory_enabled is True. Returns '' when there's nothing
    stored yet (a brand new user, or memory just turned on) so callers can
    always safely append this to a system prompt."""
    from chat.models import UserFact

    facts = list(UserFact.objects.filter(user=user).values_list("fact", flat=True)[:limit])
    if not facts:
        return ""
    bullet_list = "\n".join(f"- {fact}" for fact in facts)
    return f"What you already know about this user from earlier conversations:\n{bullet_list}"
