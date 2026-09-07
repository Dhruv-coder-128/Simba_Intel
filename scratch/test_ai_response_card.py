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

def test_ai_response_card():
    print("Testing AI Response Card & Container Architecture...")
    rf = RequestFactory()
    user, _ = User.objects.get_or_create(username="card_tester")
    session, _ = ChatSession.objects.get_or_create(user=user, title="AI Response Card Test")
    
    messages_data = [
        {
            "user_message_id": "msg-u-1",
            "user_query": "Explain quantum computing briefly",
            "user_attachments": [],
            "id": "msg-a-1",
            "role": "assistant",
            "ai_response": "### Quantum Computing Overview\n\nQuantum computing harnesses **qubits** to perform complex calculations in superposition.\n\n- Superposition\n- Entanglement\n- Quantum Interference",
            "latency": "1.8",
            "model": "quantum-core",
            "extra_data": None
        }
    ]
    
    request = rf.get(f"/?session={session.id}")
    request.user = user
    
    models = list_available_models()
    context = {
        "request": request,
        "models": models,
        "selected_model": "quantum-core",
        "selected_model_display_name": "Quantum Core",
        "messages": messages_data,
        "current_session": session,
        "favorite_sessions": [],
        "pinned_sessions": [],
        "recent_sessions": [],
        "csrf_token": "dummy_token",
    }
    
    html = render_to_string("chat.html", context, request=request)
    
    # Check 1: AI response card structure in HTML
    assert 'class="chat-block simba-block"' in html
    assert 'SIMBA_RESPONSE' in html
    assert '<div class="content markdown-content">' in html
    assert 'class="reply-actions"' in html
    print("[OK] Assistant message markup hierarchy verified.")
    
    # Check 2: AI response card CSS rules
    assert '.simba-block .content {' in html
    assert 'border-radius: var(--radius-lg, 16px);' in html
    assert 'padding: 18px 22px;' in html
    assert 'backdrop-filter: blur(12px);' in html
    print("[OK] Assistant response card styling (elevated surface, border, padding, radius, shadow) verified.")
    
    # Check 3: User message bubble styling preserved
    assert '.user-block {' in html
    assert 'width: fit-content;' in html
    assert 'max-width: min(84%, 780px);' in html
    assert '.user-block .content {' in html
    assert 'display: inline-block;' in html
    print("[OK] User message bubble sizing rules strictly preserved.")

if __name__ == "__main__":
    test_ai_response_card()
    print("\nALL AI RESPONSE CARD VERIFICATION CHECKS PASSED!")
