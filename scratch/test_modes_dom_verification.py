import os, sys
sys.path.insert(0, os.path.abspath('.'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'simba_web.settings_sqlite_export')
import django
django.setup()

from django.template.loader import render_to_string
from django.test import RequestFactory
from django.contrib.auth.models import AnonymousUser, User
from chat.models import UserProfile

factory = RequestFactory()

# Mock user
try:
    user = User.objects.filter(is_superuser=True).first()
    if not user:
        user = User.objects.first()
    if not user:
        user = User.objects.create_user(username='testverifier', email='test@simbaintel.com')
except Exception:
    user = User(username='testverifier', email='test@simbaintel.com')

profile = UserProfile.get_or_create_for(user)

def test_mode(session_type, has_messages=False):
    req = factory.get(f'/?type={session_type}')
    req.user = user
    ctx = {
        'request': req,
        'user': user,
        'profile': profile,
        'session_type': session_type,
        'messages': [{'user_query': 'hello', 'content': 'hi'}] if has_messages else [],
        'sessions': [],
        'pinned_sessions': [],
        'favorite_sessions': [],
        'other_sessions': [],
        'grouped_sessions': {},
        'models': [{'id': 'ox-alpha', 'name': 'Ox Alpha'}],
        'selected_model': 'ox-alpha',
        'is_pc_connected': False,
        'pc_telemetry': {},
        'assistant_context_sessions': [],
        'csrf_token': 'dummy_csrf',
    }
    html = render_to_string('chat.html', ctx, request=req)
    return html

print("--- Testing Assistant Mode ---")
html_assistant = test_mode('assistant')
assert 'id="agentTaskHistoryDrawer"' not in html_assistant, "CRITICAL: id=agentTaskHistoryDrawer MUST NOT be in Assistant HTML!"
assert 'id="agentWorkspace"' not in html_assistant, "CRITICAL: id=agentWorkspace MUST NOT be in Assistant HTML!"
assert 'id="voiceWorkspace"' not in html_assistant, "CRITICAL: id=voiceWorkspace MUST NOT be in Assistant HTML!"
assert 'id="qcHome"' in html_assistant, "qcHome must be in Assistant HTML when no messages!"
print("[OK] Assistant Mode verification PASSED: zero Agent/Voice contamination!")

print("--- Testing Voice Agent Mode ---")
html_voice = test_mode('voice')
assert 'id="agentTaskHistoryDrawer"' not in html_voice, "CRITICAL: id=agentTaskHistoryDrawer MUST NOT be in Voice HTML!"
assert 'id="agentWorkspace"' not in html_voice, "CRITICAL: id=agentWorkspace MUST NOT be in Voice HTML!"
assert 'id="voiceWorkspace"' in html_voice, "voiceWorkspace must be in Voice HTML!"
assert 'id="voiceMainMicBtn"' in html_voice, "voiceMainMicBtn must be in Voice HTML!"
assert 'id="voiceTranscriptCard"' in html_voice, "voiceTranscriptCard must be in Voice HTML!"
assert 'id="voiceResponseCard"' in html_voice, "voiceResponseCard must be in Voice HTML!"
assert 'id="qcHome"' not in html_voice, "qcHome must NOT be in Voice HTML!"
print("[OK] Voice Agent Mode verification PASSED: full Voice stage, zero Agent History contamination!")

print("--- Testing Agent Mode (empty) ---")
html_agent = test_mode('agent')
assert 'id="agentWorkspace"' in html_agent, "agentWorkspace must be in Agent HTML!"
assert 'id="agentTaskHistoryDrawer"' in html_agent, "agentTaskHistoryDrawer MUST be in Agent HTML!"
assert 'id="agentHistoryOverlay"' in html_agent, "agentHistoryOverlay MUST be in Agent HTML!"
assert 'SYSTEM STATUS' in html_agent, "SYSTEM STATUS section must be in Agent HTML!"
assert 'CURRENT TASK' in html_agent, "CURRENT TASK section must be in Agent HTML!"
assert 'id="agentEmptyTaskCard"' in html_agent, "agentEmptyTaskCard must be in Agent HTML!"
assert 'id="agentActiveTaskCard"' in html_agent, "agentActiveTaskCard must be in Agent HTML!"
assert 'QUICK TASKS' in html_agent, "QUICK TASKS section must be in Agent HTML!"
assert 'Open YouTube and search Roblox' in html_agent, "Quick task 1 must be present!"
assert 'Open VS Code, create calculator.py, and save it' in html_agent, "Quick task 2 must be present!"
assert 'id="voiceWorkspace"' not in html_agent, "voiceWorkspace must NOT be in Agent HTML!"
assert 'id="qcHome"' not in html_agent, "qcHome must NOT be in Agent HTML!"
print("[OK] Agent Mode (empty) verification PASSED: complete HUD layout, Task History drawer strictly scoped!")

print("--- Testing Agent Mode (with messages) ---")
html_agent_msgs = test_mode('agent', has_messages=True)
assert 'id="agentTaskHistoryDrawer"' in html_agent_msgs, "agentTaskHistoryDrawer MUST still be accessible in Agent HTML with messages!"
assert 'id="voiceWorkspace"' not in html_agent_msgs, "voiceWorkspace must NOT be in Agent HTML with messages!"
assert 'id="qcHome"' not in html_agent_msgs, "qcHome must NOT be in Agent HTML with messages!"
print("[OK] Agent Mode (with messages) verification PASSED!")

print("\nALL MODE ISOLATION AND DOM STRUCTURE TESTS PASSED ACCORDING TO SPECIFICATIONS!")
