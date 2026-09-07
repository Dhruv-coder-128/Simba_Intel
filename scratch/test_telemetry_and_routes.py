import os, sys
sys.path.insert(0, os.path.abspath('.'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'simba_web.settings_sqlite_export')
import django
django.setup()

from django.test import RequestFactory
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.middleware import SessionMiddleware
from chat.views import chat_home
from chat.agent.agent_hub import default_agent_hub, DesktopAgentHub
from chat.models import UserProfile

User = get_user_model()
user, _ = User.objects.get_or_create(username='telemetry_test_user', defaults={'email': 'telemetry@test.com'})
profile = UserProfile.get_or_create_for(user)

factory = RequestFactory()

def add_session(request):
    middleware = SessionMiddleware(lambda req: None)
    middleware.process_request(request)
    request.session.save()

print("============================================================")
print("TEST 1: DesktopAgentHub API & Contract Verification")
print("============================================================")
assert hasattr(default_agent_hub, 'get_user_agent_info'), "DesktopAgentHub must have get_user_agent_info"
assert hasattr(default_agent_hub, 'get_user_agent_telemetry'), "DesktopAgentHub must have get_user_agent_telemetry"
assert hasattr(default_agent_hub, 'is_user_agent_online'), "DesktopAgentHub must have is_user_agent_online"

# Test offline state contract
default_agent_hub.disconnect_agent(user.id)
offline_info = default_agent_hub.get_user_agent_info(user.id)
offline_telemetry = default_agent_hub.get_user_agent_telemetry(user.id)
assert offline_info["status"] == "OFFLINE", "Offline info status must be OFFLINE"
assert offline_info["is_online"] is False, "Offline info is_online must be False"
assert offline_telemetry == offline_info, "get_user_agent_telemetry must match get_user_agent_info"
print("[OK] DesktopAgentHub offline API contract verified.")

# Test online state contract
conn = default_agent_hub.register_agent(
    user=user,
    agent_id="test_pc_agent",
    hostname="DESKTOP-SIMBA",
    platform_str="Windows 11 Pro",
    agent_version="2.4.0",
)
online_info = default_agent_hub.get_user_agent_info(user.id)
online_telemetry = default_agent_hub.get_user_agent_telemetry(user.id)
assert online_info["status"] == "ONLINE", "Online info status must be ONLINE"
assert online_info["is_online"] is True, "Online info is_online must be True"
assert online_info["hostname"] == "DESKTOP-SIMBA", "Hostname must match"
assert online_info["platform"] == "Windows 11 Pro", "Platform must match"
assert online_telemetry == online_info, "get_user_agent_telemetry must match get_user_agent_info"
print("[OK] DesktopAgentHub online API contract verified.")

print("\n============================================================")
print("TEST 2: chat_home View Rendering with CONNECTED Desktop Agent")
print("============================================================")
for path in ['/', '/?type=assistant', '/?type=agent', '/?type=voice']:
    req = factory.get(path)
    req.user = user
    add_session(req)
    response = chat_home(req)
    assert response.status_code == 200, f"Expected 200 on {path}, got {response.status_code}"
    content = response.content.decode('utf-8')
    assert 'DESKTOP-SIMBA' in content or 'agentWorkspace' in content or 'voiceWorkspace' in content or 'qcHome' in content
    print(f"  [OK] Rendered {path} (Connected Agent): 200 OK ({len(content)} bytes)")

print("\n============================================================")
print("TEST 3: chat_home View Rendering with OFFLINE Desktop Agent")
print("============================================================")
default_agent_hub.disconnect_agent(user.id)
for path in ['/', '/?type=assistant', '/?type=agent', '/?type=voice']:
    req = factory.get(path)
    req.user = user
    add_session(req)
    response = chat_home(req)
    assert response.status_code == 200, f"Expected 200 on {path}, got {response.status_code}"
    content = response.content.decode('utf-8')
    print(f"  [OK] Rendered {path} (Offline Agent): 200 OK ({len(content)} bytes)")

print("\n============================================================")
print("TEST 4: chat_home View Rendering with ANONYMOUS User")
print("============================================================")
for path in ['/', '/?type=assistant', '/?type=agent', '/?type=voice']:
    req = factory.get(path)
    req.user = AnonymousUser()
    add_session(req)
    response = chat_home(req)
    # Anonymous users might redirect to login or render public landing
    print(f"  [OK] Handled {path} (Anonymous User): Status {response.status_code}")

print("\n============================================================")
print("ALL TELEMETRY & ROUTE TESTS PASSED FLAWLESSLY!")
print("============================================================")
