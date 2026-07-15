
from chat.models import ChatSession, Message
from chat.services.message_tree import walk_active_chain
from typing import List, Dict


def messages_to_history_dicts(chain: List[Message], limit: int = 10) -> List[Dict[str, str]]:
    """Convert a chronological chain of Message nodes into the role/content
    dict shape providers expect. Shared by the normal send flow (walking the
    session's active leaf) and by regenerate/edit (walking from an arbitrary
    historical message's parent, which may not be the current active leaf).
    """
    # Each turn is one user node + one assistant node, so `limit` turns is
    # `limit * 2` nodes - preserves the exact semantics of the old
    # ChatMessage-based implementation this replaces (including taking the
    # OLDEST `limit` turns, not the most recent - unchanged on purpose here;
    # a separate concern from the schema migration).
    chain = chain[:limit * 2]

    history = []
    for msg in chain:
        if msg.role == "user":
            history.append({"role": "user", "content": msg.content or ""})
            continue

        if msg.role != "assistant":
            continue

        content = (msg.content or "").strip()
        if not content:
            # Image-generation turns store no text response; describe what
            # happened instead of sending an empty assistant message upstream.
            if isinstance(msg.extra_data, dict) and msg.extra_data.get("type") == "image":
                fallback_prompt = msg.parent.content if msg.parent else ""
                prompt = msg.extra_data.get("prompt") or fallback_prompt
                content = f"[Generated an image for: {prompt}]"
            else:
                continue
        history.append({"role": "assistant", "content": content})
    return history


def get_conversation_history(session: ChatSession, limit: int = 10) -> List[Dict[str, str]]:
    return messages_to_history_dicts(walk_active_chain(session), limit=limit)


SYSTEM_PROMPT = """You are Simba, a professional, friendly AI assistant created by Dhruv.
Provide helpful, concise, and accurate responses.
Use markdown when appropriate for formatting code, lists, etc.
"""


def build_messages(
    user_query: str,
    history: List[Dict[str, str]] = None,
    system_prompt: str = SYSTEM_PROMPT
) -> List[Dict[str, str]]:
    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_query})
    return messages
