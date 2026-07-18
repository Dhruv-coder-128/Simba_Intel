
from collections import defaultdict
from types import SimpleNamespace
from typing import List, Optional

from chat.models import ChatSession, Message


def _fetch_session_messages_by_id(session_id):
    """A session's full message set as an {id: Message} map, ordered by
    created_at (dict insertion order preserves this, same as an explicit
    list) - the shared fetch behind walk_chain_from and build_display_
    messages, so a session with a long history is never queried for its
    whole message set twice in the same call. select_related('parent') so
    messages_to_history_dicts' `msg.parent.content` fallback (empty-content
    image turns) doesn't cost one extra query per occurrence either."""
    return {
        m.id: m
        for m in Message.objects.filter(session_id=session_id).select_related('parent').order_by('created_at')
    }


def _walk_chain(node: Optional[Message], by_id: dict) -> List[Message]:
    if node is None:
        return []
    chain = []
    current = by_id.get(node.id, node)
    while current is not None:
        chain.append(current)
        current = by_id.get(current.parent_id)
    chain.reverse()
    return chain


def walk_chain_from(node: Optional[Message]) -> List[Message]:
    """Walk from an arbitrary node back to the root, returning nodes in
    chronological (oldest-first) order. This is the single source of truth
    for "what's the context up to this point" - used both for the session's
    current active branch (walk_active_chain) and for regenerating/editing
    an arbitrary historical message, which needs the context as of *that*
    message, not necessarily the session's current active_leaf.

    Fetches the whole session's messages in one query and walks an in-memory
    id map, rather than following `.parent` one hop (one query) at a time -
    this runs on every AI request (get_conversation_history), so a long
    conversation would otherwise cost one DB round trip per message in the
    chain just to assemble context."""
    if node is None:
        return []
    by_id = _fetch_session_messages_by_id(node.session_id)
    return _walk_chain(node, by_id)


def walk_active_chain(session: ChatSession) -> List[Message]:
    """Walk from the session's active leaf back to the root. This is what's
    "on the currently-visible branch" - memory.py's context assembly (run on
    every single AI request), chat_home's page render, and every later
    context-injection feature all walk the same way.

    Goes by session.id/session.active_leaf_id (both already-loaded plain
    columns, zero queries) rather than session.active_leaf (the actual
    related Message object, which - if not already cached on `session` -
    would cost its own separate query before the walk even starts)."""
    if session.active_leaf_id is None:
        return []
    by_id = _fetch_session_messages_by_id(session.id)
    return _walk_chain(by_id.get(session.active_leaf_id), by_id)


def build_display_messages(session: ChatSession) -> List[SimpleNamespace]:
    """Re-pair consecutive user/assistant nodes on the active chain into
    ChatMessage-shaped objects (.id, .user_message_id, .user_query,
    .ai_response, .latency, .extra_data) so chat.html's existing render loop
    needs zero changes for the read path. `.id` is the assistant node's id
    (what "regenerate" targets); `.user_message_id` is the paired user node's
    id (what "edit" targets) - kept distinct since a template referencing the
    wrong one would silently regenerate/edit the wrong branch point. Orphaned/
    unpaired nodes (shouldn't normally happen given append_turn always
    creates them in pairs) are skipped defensively rather than raising, so a
    malformed one-off never breaks the whole page render.

    Also attaches sibling-branch info (assistant_sibling_ids/index/count,
    user_sibling_ids/index/count) so the template can render a "1/3" switcher
    wherever regenerate/edit created alternate branches - computed from the
    same one fetch of the whole session's tree the active chain itself
    already needed (not a second query over the same rows, and not one
    query per displayed message either).
    """
    if session.active_leaf_id is None:
        return []
    by_id = _fetch_session_messages_by_id(session.id)
    # by_id.get(...) instead of session.active_leaf: the leaf is guaranteed
    # to already be in by_id (it belongs to this same session), so this
    # avoids yet another query just to fetch that one row on its own.
    chain = _walk_chain(by_id.get(session.active_leaf_id), by_id)
    if not chain:
        return []

    children_by_parent = defaultdict(list)
    for msg in by_id.values():
        children_by_parent[msg.parent_id].append(msg)

    display = []
    pending_user = None
    for node in chain:
        if node.role == "user":
            pending_user = node
        elif node.role == "assistant" and pending_user is not None:
            assistant_siblings = [
                m.id for m in children_by_parent[pending_user.id] if m.role == "assistant"
            ]
            user_siblings = [
                m.id for m in children_by_parent[pending_user.parent_id] if m.role == "user"
            ]
            display.append(SimpleNamespace(
                id=node.id,
                user_message_id=pending_user.id,
                user_query=pending_user.content,
                ai_response=node.content,
                latency=node.latency,
                extra_data=node.extra_data,
                assistant_sibling_ids=assistant_siblings,
                assistant_sibling_index=(
                    assistant_siblings.index(node.id) + 1 if node.id in assistant_siblings else 1
                ),
                assistant_sibling_count=len(assistant_siblings),
                user_sibling_ids=user_siblings,
                user_sibling_index=(
                    user_siblings.index(pending_user.id) + 1 if pending_user.id in user_siblings else 1
                ),
                user_sibling_count=len(user_siblings),
            ))
            pending_user = None
        # role == "tool" or an unpaired node: not renderable by the current
        # template, intentionally skipped (future phases add their own UI).
    return display


def create_message(
    session: ChatSession,
    role: str,
    content: str,
    parent: Optional[Message] = None,
    extra_data: Optional[dict] = None,
    latency: Optional[float] = None,
) -> Message:
    return Message.objects.create(
        session=session, role=role, content=content or "",
        parent=parent, extra_data=extra_data, latency=latency,
    )


def set_active_leaf(session: ChatSession, message: Message) -> None:
    session.active_leaf = message
    session.save(update_fields=["active_leaf"])


# `None` is a legitimate parent value (the root of a new branch), so it can't
# double as "caller didn't pass anything" - a dedicated sentinel keeps those
# two cases distinguishable.
_UNSET = object()


def append_turn(
    session: ChatSession,
    user_content: str,
    assistant_content: str = "",
    assistant_extra_data: Optional[dict] = None,
    latency: Optional[float] = None,
    parent=_UNSET,
) -> tuple[Message, Message]:
    """Append a new user+assistant turn to the tree and advance the active
    leaf to the new assistant node.

    `parent` defaults to the session's current active_leaf (the normal case:
    continuing the currently-visible conversation). Pass an explicit `parent`
    (including `None`, for branching off the very first message) to branch
    from elsewhere in the tree - this is exactly how editing a past user
    message works: it creates a sibling of the old node under the same
    parent, then a fresh reply as that sibling's child.
    """
    if parent is _UNSET:
        parent = session.active_leaf
    user_msg = create_message(session, "user", user_content, parent=parent)
    assistant_msg = create_message(
        session, "assistant", assistant_content,
        parent=user_msg, extra_data=assistant_extra_data, latency=latency,
    )
    set_active_leaf(session, assistant_msg)
    return user_msg, assistant_msg


def regenerate_assistant_reply(
    old_assistant_msg: Message,
    content: str,
    extra_data: Optional[dict] = None,
    latency: Optional[float] = None,
) -> Message:
    """Create a new sibling assistant reply under the same user parent as
    old_assistant_msg (the message being regenerated), and make it the
    active leaf. The old reply stays in the DB, just off the active path."""
    session = old_assistant_msg.session
    new_msg = create_message(
        session, "assistant", content,
        parent=old_assistant_msg.parent, extra_data=extra_data, latency=latency,
    )
    set_active_leaf(session, new_msg)
    return new_msg
