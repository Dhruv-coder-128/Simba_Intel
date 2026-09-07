import os, sys
sys.path.insert(0, os.path.abspath('.'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'simba_web.settings_sqlite_export')
import django
django.setup()

from django.template.loader import render_to_string
from django.test import RequestFactory
from django.contrib.auth.models import User
from chat.models import UserProfile

user = User.objects.first()
if not user:
    user = User.objects.create_user(username='testverifier', email='test@simbaintel.com')
profile = UserProfile.get_or_create_for(user)

factory = RequestFactory()

def render_mode(mode):
    req = factory.get(f'/?type={mode}')
    req.user = user
    ctx = {
        'request': req,
        'user': user,
        'profile': profile,
        'session_type': mode,
        'messages': [],
        'sessions': [],
        'pinned_sessions': [],
        'favorite_sessions': [],
        'other_sessions': [],
        'grouped_sessions': {},
        'models': [{'id': 'ox-alpha', 'name': 'Ox Alpha'}],
        'selected_model': 'ox-alpha',
        'is_pc_connected': False,
        'pc_telemetry': {},
        'assistant_context_sessions': [{'id': 1, 'title': 'Project Research'}],
        'csrf_token': 'dummy_csrf',
    }
    return render_to_string('chat.html', ctx, request=req)

agent_html = render_mode('agent')
with open('scratch/agent_rendered.html', 'w', encoding='utf-8') as f:
    f.write(agent_html)
print(f"Exported scratch/agent_rendered.html ({len(agent_html)} bytes)")

voice_html = render_mode('voice')
with open('scratch/voice_rendered.html', 'w', encoding='utf-8') as f:
    f.write(voice_html)
print(f"Exported scratch/voice_rendered.html ({len(voice_html)} bytes)")
