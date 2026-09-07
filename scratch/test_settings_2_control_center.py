import os
import sys
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "simba_web.settings")
django.setup()

from django.test import RequestFactory, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone
from chat.models import UserProfile, UserFact, UserSession
from chat.views import profile_settings, settings_export, settings_import, settings_reset

User = get_user_model()

def test_settings_2_control_center():
    print("Testing Settings 2.0 Control Center Upgrade...")
    user, _ = User.objects.get_or_create(username="settings_v2_tester", defaults={"email": "v2tester@example.com"})
    user.set_password("pass1234")
    user.save()

    profile = UserProfile.get_or_create_for(user)
    profile.email_verified_at = timezone.now()
    profile.save()

    client = Client()
    client.force_login(user)

    # 1. GET Settings Control Center
    resp = client.get(reverse("profile_settings"))
    assert resp.status_code == 200
    html = resp.content.decode("utf-8")

    assert "SIMBA INTEL CONTROL CENTER" in html
    assert "SYSTEM SYNCHRONIZED" in html
    assert "globalSettingsSearch" in html
    assert "searchResultsDropdown" in html
    assert "overview-dashboard" in html
    assert "Model Explorer &amp; Capabilities" in html or "Model Explorer & Capabilities" in html
    assert "modelInspectorModal" in html
    assert "Voice Agent &amp; Audio Synthesis" in html or "Voice Agent & Audio Synthesis" in html
    assert "Keyboard Shortcuts Reference" in html
    assert "Accessibility Center" in html
    assert "SIMBA Desktop Agent" in html
    assert "Connected Devices &amp; Sessions" in html or "Connected Devices & Sessions" in html
    assert "Workspace Data &amp; Portability" in html or "Workspace Data & Portability" in html
    assert "Destructive Actions &amp; Reset" in html or "Destructive Actions & Reset" in html
    print("[OK] Settings 2.0 Control Center page structure and interactive modules verified.")

    # 2. Form POST update
    post_data = {
        "display_name": "Senior AI Architect",
        "default_model": "sky-net",
        "theme": "nord",
        "timezone": "UTC",
        "memory_enabled": "on",
        "notifications_enabled": "on",
        "screen_awareness_enabled": "on",
        "accent_override": "cyan",
        "density": "comfortable",
        "card_radius": "rounded",
        "animation_level": "full",
        "glass_intensity": "high",
    }
    post_resp = client.post(reverse("profile_settings"), post_data)
    assert post_resp.status_code == 302
    profile.refresh_from_db()
    assert profile.display_name == "Senior AI Architect"
    assert profile.default_model == "sky-net"
    assert profile.theme == "nord"
    assert profile.timezone == "UTC"
    assert profile.glass_intensity == "high"
    print("[OK] Settings form POST persistence verified.")

    # 3. Settings Export
    export_resp = client.get(reverse("settings_export"))
    assert export_resp.status_code == 200
    export_json = json.loads(export_resp.content.decode("utf-8"))
    assert export_json["version"] == "2.0"
    assert export_json["preferences"]["display_name"] == "Senior AI Architect"
    assert export_json["preferences"]["theme"] == "nord"
    # Ensure no secrets in export
    assert "password" not in export_json["preferences"]
    assert "agent_token" not in export_json["preferences"]
    print("[OK] Settings JSON export verified with secret isolation.")

    # 4. Settings Import
    import_payload = {
        "preferences": {
            "display_name": "Imported Architect",
            "theme": "matrix-green",
            "accent_override": "green",
            "density": "compact",
            "default_model": "cyber-max",
            "timezone": "America/New_York",
            "memory_enabled": False,
        }
    }
    import_resp = client.post(
        reverse("settings_import"),
        data=json.dumps(import_payload),
        content_type="application/json"
    )
    assert import_resp.status_code == 200
    assert import_resp.json()["status"] == "success"
    profile.refresh_from_db()
    assert profile.display_name == "Imported Architect"
    assert profile.theme == "matrix-green"
    assert profile.accent_override == "green"
    assert profile.density == "compact"
    assert profile.default_model == "cyber-max"
    assert profile.timezone == "America/New_York"
    assert profile.memory_enabled is False
    print("[OK] Settings JSON import and validation verified.")

    # 5. Settings Reset
    reset_resp = client.post(reverse("settings_reset"))
    assert reset_resp.status_code == 200
    assert reset_resp.json()["status"] == "success"
    profile.refresh_from_db()
    assert profile.theme == "cyberpunk"
    assert profile.accent_override == ""
    assert profile.density == "comfortable"
    print("[OK] Settings factory reset verified.")

    # 6. Voice Settings API
    voice_get = client.get("/api/voice/settings/")
    assert voice_get.status_code == 200
    voice_post = client.post(
        "/api/voice/settings/",
        data=json.dumps({"voice_name": "Alex", "rate": 1.2, "pitch": 1.1, "volume": 0.9}),
        content_type="application/json"
    )
    assert voice_post.status_code == 200
    assert voice_post.json()["settings"]["voice_name"] == "Alex"
    assert voice_post.json()["settings"]["rate"] == 1.2
    print("[OK] Voice Studio session settings API verified.")

if __name__ == "__main__":
    test_settings_2_control_center()
    print("\nALL SETTINGS 2.0 CONTROL CENTER CHECKS PASSED SUCCESSFULLY!")
