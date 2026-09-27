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
from chat.models import UserProfile

user = User.objects.first()
profile = UserProfile.get_or_create_for(user)

rf = RequestFactory()
req = rf.get('/?type=voice')
req.user = user

class MockMsg:
    def __init__(self, q, r, ts="12:00 PM"):
        self.user_query = q
        self.ai_response = r
        self.timestamp = ts

mock_messages = [
    MockMsg("hello how are you", "Hello! I am doing great-thanks for asking. How can I assist you today?"),
]

html_voice = render_to_string('chat.html', {
    'request': req,
    'user': user,
    'profile': profile,
    'session_type': 'voice',
    'messages': mock_messages,
    'selected_model': 'auto',
    'models': [],
    'csrf_token': 'dummy',
    'is_pc_connected': False
})

idx = 0
while True:
    pos = html_voice.find('class="chat-block user-block"', idx)
    if pos == -1: break
    print(f"Match at {pos}:")
    print(html_voice[max(0, pos-150):min(len(html_voice), pos+200)])
    print('==='*15)
    idx = pos + 1
