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

def test_composer_layout_and_rules():
    print("Testing Composer Architecture & Layout Stability...")
    rf = RequestFactory()
    user, _ = User.objects.get_or_create(username="composer_test_user")
    session, _ = ChatSession.objects.get_or_create(user=user, title="Composer Stability Test")
    
    request = rf.get(f"/?session={session.id}")
    request.user = user
    
    models = list_available_models()
    context = {
        "request": request,
        "models": models,
        "selected_model": "auto",
        "selected_model_display_name": "Auto",
        "messages": [],
        "current_session": session,
        "favorite_sessions": [],
        "pinned_sessions": [],
        "recent_sessions": [],
        "csrf_token": "dummy_token",
    }
    
    html = render_to_string("chat.html", context, request=request)
    
    # Check 1: Composer shell and command box structure
    assert '<div id="input-wrapper">' in html, "input-wrapper ID missing"
    assert '<div class="composer-shell">' in html, "composer-shell class missing"
    assert '<div class="command-box">' in html, "command-box class missing"
    assert '<textarea id="user-input"' in html, "user-input textarea missing"
    
    # Check 2: Authoritative autoResizeComposerInput function presence
    assert 'function autoResizeComposerInput(' in html, "autoResizeComposerInput missing in JS"
    
    # Check 3: CSS rules for authoritative composer dimensions
    assert '#user-input {' in html, "#user-input CSS missing"
    assert 'min-height: 36px;' in html or 'height: 36px;' in html, "#user-input 36px height rule missing"
    assert 'max-height: 140px;' in html, "#user-input max-height rule missing"
    assert 'box-sizing: border-box;' in html, "box-sizing missing in composer CSS"
    
    # Check 4: Chat flow independent scrolling
    assert '#chat-flow {' in html, "#chat-flow CSS missing"
    assert 'overflow-y: auto;' in html, "#chat-flow overflow-y missing"
    
    # Check 5: Dropdown overlay and scroll constraint
    assert '.cyber-options {' in html, ".cyber-options CSS missing"
    assert 'position: absolute;' in html, ".cyber-options position absolute missing"
    assert '.model-dropdown-scroll {' in html, ".model-dropdown-scroll CSS missing"
    assert 'overflow-y: auto;' in html, ".model-dropdown-scroll overflow-y missing"
    
    print("[OK] Composer HTML, CSS, and JS structure verified successfully.")

if __name__ == "__main__":
    test_composer_layout_and_rules()
    print("\nALL COMPOSER STABILITY CHECKS PASSED!")
