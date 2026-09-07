import os
import sys
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "simba_web.settings")
django.setup()

from django.template.loader import render_to_string
from django.test import RequestFactory
from django.contrib.auth import get_user_model
from chat.models import ChatSession, Message
from chat.views import message_info
from chat.services.model_registry import list_available_models

User = get_user_model()

def test_template_rendering_and_info_buttons():
    print("Testing chat.html template rendering and info buttons...")
    rf = RequestFactory()
    user, _ = User.objects.get_or_create(username="test_verify_user_2")
    session, _ = ChatSession.objects.get_or_create(user=user, title="Test Session")
    
    # Create test messages: one with stats, one without
    msg_with_stats, _ = Message.objects.get_or_create(
        session=session,
        role="assistant",
        content="### Sample Heading\n**Bold response**\n```python\nprint('hello world')\n```",
        extra_data={"stats": {"provider": "Groq", "actual_model": "llama-3.3-70b", "input_tokens": 42, "output_tokens": 128, "total_tokens": 170, "response_time_s": 0.65, "ttft_s": 0.12}}
    )
    
    msg_without_stats, _ = Message.objects.get_or_create(
        session=session,
        role="assistant",
        content="Plain response without extra stats",
        extra_data=None
    )
    
    request = rf.get(f"/?session={session.id}")
    request.user = user
    
    models = list_available_models()
    context = {
        "request": request,
        "models": models,
        "selected_model": "auto",
        "selected_model_display_name": "Auto",
        "messages": [
            {
                "id": msg_with_stats.id,
                "role": "assistant",
                "ai_response": msg_with_stats.content,
                "extra_data": msg_with_stats.extra_data,
            },
            {
                "id": msg_without_stats.id,
                "role": "assistant",
                "ai_response": msg_without_stats.content,
                "extra_data": msg_without_stats.extra_data,
            }
        ],
        "current_session": session,
        "favorite_sessions": [],
        "pinned_sessions": [],
        "recent_sessions": [],
        "csrf_token": "dummy_token",
    }
    
    html = render_to_string("chat.html", context, request=request)
    assert 'id="messageInfoOverlay"' in html, "messageInfoOverlay missing in HTML"
    assert 'class="command-palette-overlay message-info-overlay"' in html, "messageInfoOverlay class missing"
    assert 'onclick="openMessageInfo(this)"' in html, "openMessageInfo onclick handler missing"
    assert 'formatAllMessages()' in html, "formatAllMessages() missing in HTML"
    assert 'formatMessageBlock(block)' in html, "formatMessageBlock missing in HTML"
    assert f'data-message-id="{msg_with_stats.id}"' in html, "data-message-id missing on assistant block"
    assert f'data-message-id="{msg_without_stats.id}"' in html, "data-message-id missing on second assistant block"
    print("[OK] chat.html rendered cleanly with all message blocks and info buttons.")

def test_message_info_endpoint():
    print("Testing /messages/<id>/info/ view...")
    rf = RequestFactory()
    user, _ = User.objects.get_or_create(username="test_verify_user_2")
    session, _ = ChatSession.objects.get_or_create(user=user, title="Test Session")
    
    msg_with_stats, _ = Message.objects.get_or_create(
        session=session,
        role="assistant",
        content="Test content with stats",
        extra_data={"stats": {"provider": "Groq", "actual_model": "llama-3.3-70b", "input_tokens": 50, "output_tokens": 100, "total_tokens": 150, "response_time_s": 0.8}}
    )
    
    req1 = rf.get(f"/messages/{msg_with_stats.id}/info/")
    req1.user = user
    resp1 = message_info(req1, msg_with_stats.id)
    assert resp1.status_code == 200, f"Expected 200, got {resp1.status_code}"
    data1 = json.loads(resp1.content.decode("utf-8"))
    assert data1["status"] == "success", "Expected status success"
    assert data1["has_stats"] is True, "Expected has_stats True"
    assert data1["stats"]["message_id"] == msg_with_stats.id
    assert data1["stats"]["provider"] == "Groq"
    assert data1["stats"]["total_tokens"] == 150
    print(f"[OK] message_info for message with stats: {data1['stats']['actual_model']} (Tokens: {data1['stats']['total_tokens']})")
    
    # Message without stats (should still return valid metadata without failing)
    msg_without_stats, _ = Message.objects.get_or_create(
        session=session,
        role="assistant",
        content="Test content without stats",
        extra_data=None
    )
    req2 = rf.get(f"/messages/{msg_without_stats.id}/info/")
    req2.user = user
    resp2 = message_info(req2, msg_without_stats.id)
    assert resp2.status_code == 200, f"Expected 200, got {resp2.status_code}"
    data2 = json.loads(resp2.content.decode("utf-8"))
    assert data2["status"] == "success"
    assert data2["has_stats"] is True
    assert data2["stats"]["message_id"] == msg_without_stats.id
    assert data2["stats"]["message_type"] == "TEXT"
    assert data2["stats"]["input_tokens"] is None  # Clean None -> displays "Not available" in frontend
    print(f"[OK] message_info for restored message without extra_data stats: #{data2['stats']['message_id']} ({data2['stats']['message_type']})")

if __name__ == "__main__":
    test_template_rendering_and_info_buttons()
    test_message_info_endpoint()
    print("\nALL VERIFICATION TESTS PASSED SUCCESSFULLY!")
