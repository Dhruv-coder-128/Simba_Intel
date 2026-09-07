import os
import sys
import json
import django

sys.path.insert(0, os.path.abspath('.'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'simba_web.settings')
django.setup()

from django.test import Client
from django.contrib.auth import get_user_model
from chat.models import ChatSession, Message, UserFact, ConversationHighlight, SavedPrompt

User = get_user_model()
user, _ = User.objects.get_or_create(username='api_test_user', defaults={'email': 'api_test@test.com'})
user.set_password('TestPass123!')
user.save()

client = Client()
client.force_login(user)

print("=== TESTING PHASE 4 API ENDPOINTS ===")

# 1. Memory List
res = client.get('/account/memory/')
assert res.status_code == 200
data = res.json()
print("1. GET /account/memory/: Status 200, keys:", list(data.keys()))

# 2. Memory Create
res = client.post('/account/memory/create/', {'fact': 'Prefers dark mode', 'category': 'preference'})
assert res.status_code == 200
mem_id = res.json()['memory']['id']
print(f"2. POST /account/memory/create/: Status 200, created id={mem_id}")

# 3. Memory Delete
res = client.post(f'/account/memory/{mem_id}/delete/')
assert res.status_code == 200
print(f"3. POST /account/memory/{mem_id}/delete/: Status 200")

# 4. Highlight Create & List
session = ChatSession.objects.create(user=user, title="API Test Chat")
res = client.post('/highlights/create/', {
    'session_id': session.id,
    'title': 'Test Highlight',
    'content': 'Test content snippet',
    'type': 'decision',
})
assert res.status_code == 200
h_id = res.json()['highlight']['id']
print(f"4. POST /highlights/create/: Status 200, id={h_id}")

res = client.get(f'/highlights/?session_id={session.id}')
assert res.status_code == 200
print(f"5. GET /highlights/?session_id={session.id}: Status 200, count={len(res.json()['highlights'])}")

# 6. Global Search
res = client.get('/search/global/?q=API Test')
assert res.status_code == 200
results = res.json()['results']
print(f"6. GET /search/global/?q=API Test: Status 200, matched={len(results)}")

# 7. Session Export
res = client.get(f'/session/{session.id}/export/?format=markdown')
assert res.status_code == 200
print(f"7. GET /session/{session.id}/export/?format=markdown: Status 200, Content-Type={res['Content-Type']}")

res = client.get(f'/session/{session.id}/export/?format=json')
assert res.status_code == 200
print(f"8. GET /session/{session.id}/export/?format=json: Status 200, Content-Type={res['Content-Type']}")

# Cleanup
session.delete()
print("\n>>> ALL PHASE 4 API CHECKS PASSED! <<<")
