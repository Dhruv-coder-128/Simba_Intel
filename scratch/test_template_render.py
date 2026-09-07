import os
import sys
import django

sys.path.insert(0, os.path.abspath('.'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'simba_web.settings')
django.setup()

from django.template.loader import render_to_string, get_template
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from chat.models import UserProfile, ChatSession

User = get_user_model()
user, _ = User.objects.get_or_create(username='template_test_user', defaults={'email': 'template@test.com'})
profile = UserProfile.get_or_create_for(user)

factory = RequestFactory()
request = factory.get('/')
request.user = user

print("=== 1. TESTING chat.html TEMPLATE COMPILATION & RENDERING ===")
try:
    template = get_template('chat.html')
    print("chat.html get_template: SUCCESS")
    
    html = render_to_string('chat.html', {
        'request': request,
        'profile': profile,
        'sessions': [],
        'pinned_sessions': [],
        'messages': [],
        'models': [],
    }, request=request)
    print(f"chat.html render_to_string: SUCCESS (rendered {len(html)} characters)")
except Exception as e:
    print(f"chat.html render ERROR: {type(e).__name__}: {e}")
    sys.exit(1)

print("\n=== 2. TESTING profile.html TEMPLATE COMPILATION & RENDERING ===")
try:
    template = get_template('profile.html')
    print("profile.html get_template: SUCCESS")
    
    html = render_to_string('profile.html', {
        'request': request,
        'profile': profile,
        'models': [],
        'theme_choices': [],
        'accent_choices': [],
        'timezone_choices': [],
        'user_sessions': [],
        'recent_logins': [],
    }, request=request)
    print(f"profile.html render_to_string: SUCCESS (rendered {len(html)} characters)")
except Exception as e:
    print(f"profile.html render ERROR: {type(e).__name__}: {e}")
    sys.exit(1)

print("\n>>> ALL TEMPLATES COMPILED AND RENDERED FLAWLESSLY! <<<")
