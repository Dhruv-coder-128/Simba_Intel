import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'simba_web.settings')
import django
django.setup()

from django.template.loader import render_to_string
from django.test import RequestFactory
from django.contrib.auth.models import User
from chat.models import ChatSession, Message, UserProfile

user = User.objects.first()
profile = UserProfile.get_or_create_for(user)

rf = RequestFactory()

def make_req(path='/'):
    req = rf.get(path)
    req.user = user
    return req

# Mock message object for voice history test
class MockMsg:
    def __init__(self, q, r, ts="12:00 PM"):
        self.user_query = q
        self.ai_response = r
        self.timestamp = ts

mock_messages = [
    MockMsg("hello how are you", "Hello! I am doing great-thanks for asking. How can I assist you today?"),
    MockMsg("what is python", "Python is a high-level, interpreted programming language.")
]

# 1. Test Assistant Mode
html_assistant = render_to_string('chat.html', {
    'request': make_req('/'),
    'user': user,
    'profile': profile,
    'session_type': 'assistant',
    'messages': [],
    'selected_model': 'auto',
    'models': [],
    'csrf_token': 'dummy',
    'is_pc_connected': False
})
assert 'SIMBA_INTEL' in html_assistant, "Assistant mode missing title!"
assert 'id="qcHome"' in html_assistant, "qcHome missing in Assistant empty state!"
assert 'id="input-wrapper"' in html_assistant, "input-wrapper missing in Assistant mode!"
print("1. Assistant mode render: PASSED")

# 2. Test Voice Mode
html_voice = render_to_string('chat.html', {
    'request': make_req('/?type=voice'),
    'user': user,
    'profile': profile,
    'session_type': 'voice',
    'messages': mock_messages,
    'selected_model': 'auto',
    'models': [],
    'csrf_token': 'dummy',
    'is_pc_connected': False
})
assert 'VOICE AGENT' in html_voice, "Voice workspace header missing!"
assert 'id="voiceHeroStage"' in html_voice, "voiceHeroStage missing in Voice mode!"
assert 'id="voiceFeedList"' in html_voice, "voiceFeedList missing in Voice mode!"
assert 'id="input-wrapper"' not in html_voice, "input-wrapper must NOT be present in Voice mode!"
assert 'hello how are you' in html_voice, "Voice spoken history must render past user query!"
assert 'thanks for asking' in html_voice, "Voice spoken history must render past response!"
assert 'class="voice-feed-card"' in html_voice, "voice-feed-card must be present in voice feed!"

# Verify that within #chat-flow, NO chat-block is rendered in voice mode
chat_flow_voice = html_voice.split('id="chat-flow"')[1].split('<button type="button" id="btnJumpToLatest"')[0]
assert 'class="chat-block user-block"' not in chat_flow_voice, "chat-block user-block must NOT be in chat-flow in Voice mode!"
assert 'class="chat-block simba-block"' not in chat_flow_voice, "chat-block simba-block must NOT be in chat-flow in Voice mode!"
print("2. Voice mode render: PASSED")

# 3. Test Agent Mode (Connected)
html_agent_online = render_to_string('chat.html', {
    'request': make_req('/?type=agent'),
    'user': user,
    'profile': profile,
    'session_type': 'agent',
    'messages': [],
    'selected_model': 'auto',
    'models': [],
    'csrf_token': 'dummy',
    'is_pc_connected': True,
    'pc_telemetry': {'hostname': 'LENOVO-LOQ', 'platform': 'Windows 11'}
})
assert 'AGENT MODE' in html_agent_online, "Agent workspace missing in Agent mode!"
assert 'DESKTOP BRIDGE CONNECTED // LENOVO-LOQ' in html_agent_online, "Connected title missing in agent online mode!"
assert 'id="bridgeCommandPill" style="display:none;"' in html_agent_online, "bridgeCommandPill must be hidden when is_pc_connected is True!"
print("3. Agent mode (Online) render: PASSED")

# 4. Test Agent Mode (Disconnected)
html_agent_offline = render_to_string('chat.html', {
    'request': make_req('/?type=agent'),
    'user': user,
    'profile': profile,
    'session_type': 'agent',
    'messages': [],
    'selected_model': 'auto',
    'models': [],
    'csrf_token': 'dummy',
    'is_pc_connected': False
})
assert 'DESKTOP AGENT DISCONNECTED // LOCAL PC CONTROL STANDING BY' in html_agent_offline, "Disconnected title missing!"
assert 'id="bridgeCommandPill"' in html_agent_offline, "bridgeCommandPill missing in offline mode!"
assert 'style="display:none;"' not in html_agent_offline.split('id="bridgeCommandPill"')[1][:50], "bridgeCommandPill must be visible when offline!"
print("4. Agent mode (Offline) render: PASSED")

print("\n=============================================")
print("ALL 4 MODULAR CHAT RENDER TESTS PASSED 100%!")
print("=============================================")
