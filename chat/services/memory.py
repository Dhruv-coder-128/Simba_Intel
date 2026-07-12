
from chat.models import ChatSession, ChatMessage
from typing import List, Dict


def get_conversation_history(session: ChatSession, limit: int = 10) -> List[Dict[str, str]]:
    messages = ChatMessage.objects.filter(session=session).order_by('timestamp')[:limit]
    history = []
    for msg in messages:
        history.append({"role": "user", "content": msg.user_query})

        ai_response = msg.ai_response.strip() if msg.ai_response else ""
        if not ai_response:
            # Image-generation turns store no text response; describe what
            # happened instead of sending an empty assistant message upstream.
            if isinstance(msg.extra_data, dict) and msg.extra_data.get("type") == "image":
                prompt = msg.extra_data.get("prompt", msg.user_query)
                ai_response = f"[Generated an image for: {prompt}]"
            else:
                continue
        history.append({"role": "assistant", "content": ai_response})
    return history


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
