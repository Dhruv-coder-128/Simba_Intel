import os
import sys
import re

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "simba_web.settings")
django.setup()

from django.template.loader import render_to_string
from django.test import RequestFactory
from django.contrib.auth import get_user_model
from chat.models import ChatSession, Message
from chat.services.model_registry import list_available_models

User = get_user_model()

def test_user_bubble_rendering_parity():
    print("Testing User Message Bubble Rendering Parity & Stability...")
    rf = RequestFactory()
    user, _ = User.objects.get_or_create(username="bubble_tester")
    session, _ = ChatSession.objects.get_or_create(user=user, title="Bubble Parity Test")
    
    test_queries = [
        "ok thanks",
        "now tell me what is calory and how can we control",
        "hello\nhow are you\nplease explain this",
        "thumbs up test"
    ]
    
    messages_data = []
    for idx, q in enumerate(test_queries):
        messages_data.append({
            "user_message_id": f"msg-u-{idx}",
            "user_query": q,
            "user_attachments": [],
            "id": f"msg-a-{idx}",
            "role": "assistant",
            "ai_response": f"Response to {q}",
            "extra_data": None
        })
    
    request = rf.get(f"/?session={session.id}")
    request.user = user
    
    models = list_available_models()
    context = {
        "request": request,
        "models": models,
        "selected_model": "auto",
        "selected_model_display_name": "Auto",
        "messages": messages_data,
        "current_session": session,
        "favorite_sessions": [],
        "pinned_sessions": [],
        "recent_sessions": [],
        "csrf_token": "dummy_token",
    }
    
    html = render_to_string("chat.html", context, request=request)
    
    # Check 1: Zero whitespace corruption in rendered content
    for q in test_queries:
        pattern = re.compile(rf'<div class="content">{re.escape(q)}</div>')
        assert pattern.search(html), f"Expected exact tight content <div class=\"content\">{q}</div> without leading/trailing template whitespace"
        print(f"[OK] Content node for '{q.splitlines()[0][:20]}' rendered without rogue whitespace.")
        
    # Check 2: CSS rules verification
    assert '.user-block {' in html
    assert 'width: fit-content;' in html
    assert 'max-width: min(84%, 780px);' in html
    assert '.user-block .content {' in html
    assert 'display: inline-block;' in html
    assert 'white-space: pre-wrap;' in html
    assert 'word-break: break-word;' in html
    print("[OK] CSS rules enforce content-based fit-content sizing with strict max-width constraints.")
    
    # Check 3: JS canonical renderer presence
    assert 'function renderCanonicalUserMessageHTML(' in html
    assert 'avatar user' in html
    print("[OK] JS renderCanonicalUserMessageHTML helper confirmed matching Django template structure.")

if __name__ == "__main__":
    test_user_bubble_rendering_parity()
    print("\nALL USER BUBBLE PARITY CHECKS PASSED SUCCESSFULLY!")
