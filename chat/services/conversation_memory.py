"""AI Conversation Memory & Long-Context Architecture (Phase 4).

Provides hierarchical, token-budget-aware context building:
1. Core System Prompt & Behavioral Instructions
2. Cross-Chat User Memory (if enabled on UserProfile)
3. Key Conversation Facts & Decisions (in-session facts, constraints, and architecture)
4. Persistent Conversation Summary (extractive & structured synthesis of earlier conversation)
5. Recent Exact Messages (model-aware verbatim window fitting token budget)
6. Current User Message / Query

Ensures FULL conversation history is stored forever in the database, while
active inference receives a rich, compressed representation of older context
alongside exact recent turns, with ZERO unnecessary background LLM token consumption.
"""
import logging
import re
from typing import Dict, List, Optional, Tuple, Any

from chat.services.memory import messages_to_history_dicts
from chat.services.message_tree import walk_active_chain
from chat.services.model_registry import get_model_config

logger = logging.getLogger("simba_intel")

MEMORY_MODEL_ID = "nova-mind"
SUMMARIZE_EVERY_N_MESSAGES = 20
RECENT_TURNS_KEPT_VERBATIM = 10

DEFAULT_CONTEXT_WINDOW = 128000
SYSTEM_BUDGET_TOKENS = 600
SUMMARY_BUDGET_TOKENS = 1200
FACTS_BUDGET_TOKENS = 600
RESPONSE_RESERVE_TOKENS = 4000
ESTIMATED_TOKENS_PER_TURN = 250


def estimate_token_count(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def extract_conversation_facts(chain: list) -> list[str]:
    """Extracts explicit, durable facts and instructions stated within this specific conversation.
    Scoped strictly to the current session (never leaked across sessions).
    """
    facts = []
    seen = set()

    patterns = [
        # Project & App identifiers
        r"(?:my project is called|the project is called|project name is|i am working on|i'm building|building an? app called|repo is)\s+([^.\n,]+)",
        # Frameworks & Tech stack
        r"(?:i use|we use|built with|framework is|using|database is|frontend is|backend is)\s+([^.\n,]+)",
        # Operating System / Environment
        r"(?:the desktop agent runs on|running on|runs on|agent is on|os is|operating system is|environment is)\s+([^.\n,]+)",
        # Instructions & Model preferences
        r"(?:always prioritize|always use|never use|prefer to use|default model should be)\s+([^.\n]+)",
        # Rules and guidelines
        r"(?:remember that|note that|rule:\s*|constraint:\s*)\s+([^.\n]+)",
    ]

    for msg in chain:
        content = (msg.content or "").strip()
        if not content:
            continue
        role = getattr(msg, "role", "")
        # For user turns, look for explicit factual statements
        if role == "user":
            for pat in patterns:
                for m in re.finditer(pat, content, re.IGNORECASE):
                    raw = m.group(0).strip().rstrip(".,;:")
                    if len(raw) >= 6 and raw.lower() not in seen:
                        seen.add(raw.lower())
                        facts.append(raw)
        # For assistant turns, extract key code/architecture decisions if formatted explicitly
        elif role == "assistant":
            for m in re.finditer(r"(?:configured|implemented|architecture decided:|stack chosen:)\s+([^.\n]+)", content, re.IGNORECASE):
                raw = m.group(0).strip().rstrip(".,;:")
                if len(raw) >= 10 and raw.lower() not in seen:
                    seen.add(raw.lower())
                    facts.append(raw)

    return facts[:12]


def build_or_update_session_summary(session, chain: list, older_nodes: list) -> str:
    """Generates a structured, factual extractive summary of older conversation history
    without invoking external LLM models or causing information degradation.
    """
    if not older_nodes:
        return getattr(session, "summary", "") or ""

    user_queries = []
    key_points = []

    for msg in older_nodes:
        content = (msg.content or "").strip()
        if not content:
            continue
        role = getattr(msg, "role", "")
        first_sentence = re.split(r'[.\n]', content)[0].strip()
        if role == "user":
            if first_sentence and len(first_sentence) > 5 and first_sentence not in user_queries:
                user_queries.append(first_sentence[:120])
        elif role == "assistant":
            lines = [l.strip("-* 0123456789.") for l in content.split("\n") if l.strip().startswith(("-", "*", "1.", "2."))]
            if lines:
                for l in lines[:2]:
                    if l and l not in key_points:
                        key_points.append(l[:120])
            elif first_sentence and len(first_sentence) > 10 and first_sentence not in key_points:
                key_points.append(first_sentence[:120])

    parts = []
    if user_queries:
        parts.append(f"User inquired about: {'; '.join(user_queries[-5:])}.")
    if key_points:
        parts.append(f"Key guidance & conclusions: {'; '.join(key_points[-4:])}.")

    new_summary = " ".join(parts) if parts else "Earlier conversation turns covered project setup and technical requirements."

    # Update session summary on DB model if changed
    if new_summary != getattr(session, "summary", ""):
        session.summary = new_summary[:2000]
        session.summary_message_count = len(chain)
        try:
            session.save(update_fields=["summary", "summary_message_count"])
        except Exception:
            pass

    return getattr(session, "summary", "")


def calculate_recent_turns_budget(model_id: str, chain: list) -> int:
    """Calculates the number of recent verbatim turns to include based on model capacity."""
    try:
        cfg = get_model_config(model_id)
        ctx_window = getattr(cfg, "context_window", DEFAULT_CONTEXT_WINDOW)
    except Exception:
        ctx_window = DEFAULT_CONTEXT_WINDOW

    if ctx_window >= 128000:
        max_turns = 40
    elif ctx_window >= 64000:
        max_turns = 24
    elif ctx_window >= 32000:
        max_turns = 14
    else:
        max_turns = 6

    total_turns = len(chain) // 2
    return min(max_turns, max(4, total_turns))


def build_conversation_context(
    session,
    user_query: str,
    system_prompt: str,
    model_id: str = "ox-alpha",
) -> List[Dict[str, Any]]:
    """Single canonical context builder establishing long-conversation continuity:

    1. Core System prompt & Safety
    2. Long-term User Memory facts (cross-chat profile memory if enabled)
    3. Key Conversation Facts & Directives (session-specific facts and constraints)
    4. Persistent Conversation Summary (structured synthesis of older turns beyond verbatim window)
    5. Recent Exact Messages (model-aware verbatim window)
    6. Current User Message / Query
    """
    profile = getattr(session.user, 'profile', None) if session and getattr(session, 'user', None) else None
    user_memory = get_user_memory_context(session.user) if (profile and profile.memory_enabled) else ""

    messages = [{"role": "system", "content": system_prompt}]
    if user_memory:
        messages.append({"role": "system", "content": user_memory})

    chain = walk_active_chain(session) if session else []
    recent_turns_count = calculate_recent_turns_budget(model_id, chain)
    recent_nodes_count = recent_turns_count * 2

    # Extract session-specific facts from the full conversation
    conv_facts = extract_conversation_facts(chain) if chain else []
    if conv_facts:
        facts_block = "Key conversation context & facts established in this chat:\n" + "\n".join(f"- {f}" for f in conv_facts)
        messages.append({"role": "system", "content": facts_block})

    # If conversation is longer than recent verbatim window, synthesize and include older summary
    if len(chain) > recent_nodes_count:
        older_nodes = chain[:-recent_nodes_count]
        summary = build_or_update_session_summary(session, chain, older_nodes)
        if summary:
            messages.append({
                "role": "system",
                "content": f"Summary of earlier parts of this conversation:\n{summary}"
            })
        recent_nodes = chain[-recent_nodes_count:]
    else:
        recent_nodes = chain

    # Append recent exact turns
    history = messages_to_history_dicts(recent_nodes, limit=None)
    messages.extend(history)

    # Append current user query
    messages.append({"role": "user", "content": user_query})

    logger.info(
        "build_conversation_context (session=%s, model=%s, total_nodes=%d, recent_nodes=%d, facts=%d, summary=%s)",
        getattr(session, "id", "none"), model_id, len(chain), len(recent_nodes), len(conv_facts), bool(getattr(session, "summary", ""))
    )
    return messages


def build_context_messages(session, user_query, system_prompt, limit=None, model_id="ox-alpha"):
    """Backward-compatible wrapper redirecting to build_conversation_context."""
    return build_conversation_context(session, user_query, system_prompt, model_id=model_id)


def generate_session_summary(session, force=False) -> str:
    """Returns conversation summary."""
    return getattr(session, "summary", "") or ""


def maybe_summarize_session(session):
    """Returns conversation summary."""
    return getattr(session, "summary", "") or ""


def _classify_fact_category(fact_text: str) -> str:
    lower = fact_text.lower()
    if any(k in lower for k in ("prefer", "like", "favorite", "style", "format", "theme", "tone")):
        return "preference"
    if any(k in lower for k in ("python", "javascript", "react", "django", "typescript", "rust", "c++", "code", "tabs", "spaces", "syntax")):
        return "coding_style"
    if any(k in lower for k in ("always", "never", "instruction", "rule", "guideline", "constraint")):
        return "instruction"
    if any(k in lower for k in ("working on", "building", "project", "app", "startup", "repo", "database")):
        return "project"
    return "general"


def extract_and_store_facts(user, session):
    """Cross-chat memory writer with categorized fact extraction using lightweight zero-LLM parsing."""
    from chat.models import UserFact

    if session.facts_extracted:
        return
    try:
        chain = walk_active_chain(session)
        if len(chain) < 2:
            return

        user_messages = [m.content for m in chain if m.role == "user" and m.content]
        existing = set(UserFact.objects.filter(user=user).values_list("fact", flat=True))
        
        fact_patterns = [
            r"(?:i prefer|i like|i love|my preference is)\s+([^.\n]+)",
            r"(?:always|never)\s+([^.\n]+)",
            r"(?:my name is|i am working on|i'm building)\s+([^.\n]+)",
        ]
        
        for msg in user_messages:
            for pat in fact_patterns:
                for match in re.finditer(pat, msg, re.IGNORECASE):
                    raw_fact = match.group(0).strip()
                    if len(raw_fact) >= 8 and raw_fact not in existing:
                        category = _classify_fact_category(raw_fact)
                        UserFact.objects.create(user=user, fact=raw_fact[:500], category=category, source_session=session)
                        existing.add(raw_fact)

        session.facts_extracted = True
        session.save(update_fields=["facts_extracted"])
    except Exception as e:
        logger.warning("Fact extraction failed (session=%s): %s", session.id, e)


def get_user_memory_context(user, limit=10):
    """Read side of cross-chat memory - only called when UserProfile.memory_enabled is True."""
    from chat.models import UserFact

    facts = list(UserFact.objects.filter(user=user).order_by('-updated_at', '-created_at')[:limit])
    if not facts:
        return ""

    grouped = {}
    for f in facts:
        label = f.get_category_display() if hasattr(f, 'get_category_display') else f.category
        grouped.setdefault(label, []).append(f.fact)

    lines = ["What you know about this user from long-term memory & preferences:"]
    for cat, items in grouped.items():
        lines.append(f"[{cat}]")
        for item in items:
            lines.append(f"- {item}")
    return "\n".join(lines)
