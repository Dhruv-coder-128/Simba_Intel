import os
import sys
sys.path.insert(0, os.path.abspath('.'))
import django
import subprocess
import re

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'simba_web.settings')
django.setup()

from django.template.loader import render_to_string
from django.contrib.auth.models import User
from chat.models import UserProfile, ChatSession

user = User.objects.first()
if not user:
    user = User.objects.create_user('testuser', 'test@example.com', 'password123')
profile = UserProfile.get_or_create_for(user)

context = {
    'user': user,
    'profile': profile,
    'sessions': [],
    'pinned_sessions': [],
    'favorite_sessions': [],
    'other_sessions': [],
    'folders': [],
    'view_mode': 'active',
    'folder_filter': None,
    'session_type': 'assistant',
    'assistant_context_sessions': [],
    'messages': [],
    'current_session': None,
    'selected_model': 'quantum-core',
    'models_enriched': [],
    'can_access_admin_console': True,
    'agent_token': 'dummy-token',
    'agent_connected': False,
    'is_pc_connected': False,
    'pc_telemetry': {},
    'agent_task_history': [],
    'request': type('MockRequest', (), {'user': user, 'session': {}, 'META': {}})(),
}

rendered_html = render_to_string('chat.html', context)
with open('scratch/rendered_chat.html', 'w', encoding='utf-8') as f:
    f.write(rendered_html)

script_pattern = re.compile(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', re.DOTALL | re.IGNORECASE)
matches = script_pattern.findall(rendered_html)
print(f"Found {len(matches)} rendered inline script blocks.")

for idx, code in enumerate(matches, 1):
    filename = f'scratch/rendered_script_{idx}.js'
    with open(filename, 'w', encoding='utf-8') as sf:
        sf.write(code)
    res = subprocess.run(['node', '--check', filename], capture_output=True, text=True)
    if res.returncode == 0:
        print(f"Rendered Script {idx} ({len(code)} chars): SYNTAX OK")
    else:
        print(f"Rendered Script {idx} ({len(code)} chars): SYNTAX ERROR:")
        print(res.stderr)
