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
from chat.models import UserProfile, UserFact, UserSession
from chat.views import profile_settings

User = get_user_model()

def test_settings_redesign():
    print("Testing Complete Settings Page Redesign & Functionality...")
    rf = RequestFactory()
    user, _ = User.objects.get_or_create(username="settings_tester", defaults={"email": "tester@example.com"})
    user.set_password("pass1234")
    user.save()

    profile = UserProfile.get_or_create_for(user)
    profile.email_verified_at = django.utils.timezone.now()
    profile.save()

    # 1. GET Settings Dashboard
    req = rf.get(reverse("profile_settings"))
    req.user = user
    req.session = {}
    resp = profile_settings(req)
    assert resp.status_code == 200
    html = resp.content.decode("utf-8")
    assert "SETTINGS" in html
    assert "Workspace Identity" in html
    assert "Default AI Model" in html
    assert "Intelligent Memory Console" in html
    assert "Color Themes" in html
    assert "SIMBA Desktop Agent" in html
    assert "Account Security" in html
    assert "Destructive Actions" in html
    print("[OK] Settings page renders all 8 premium sections.")

    # 2. POST Save Settings
    post_data = {
        "display_name": "Antigravity Engineer",
        "default_model": "sky-net",
        "theme": "matrix-green",
        "timezone": "America/New_York",
        "memory_enabled": "on",
        "notifications_enabled": "on",
        "screen_awareness_enabled": "on",
        "accent_override": "green",
        "density": "compact",
        "card_radius": "rounded",
        "animation_level": "reduced",
        "glass_intensity": "high",
    }
    req_post = rf.post(reverse("profile_settings"), post_data)
    req_post.user = user
    req_post.session = {}
    resp_post = profile_settings(req_post)
    assert resp_post.status_code == 302

    profile.refresh_from_db()
    assert profile.display_name == "Antigravity Engineer"
    assert profile.default_model == "sky-net"
    assert profile.theme == "matrix-green"
    assert profile.timezone == "America/New_York"
    assert profile.timezone_auto is False
    assert profile.memory_enabled is True
    assert profile.notifications_enabled is True
    assert profile.screen_awareness_enabled is True
    assert profile.accent_override == "green"
    assert profile.density == "compact"
    assert profile.animation_level == "reduced"
    assert profile.glass_intensity == "high"
    print("[OK] Settings form POST persistence verified across all preferences.")

    # 3. Memory CRUD via Client
    client = Client()
    client.force_login(user)

    # Create memory fact
    create_resp = client.post("/account/memory/create/", {
        "fact": "Always use strict typing in Python",
        "category": "coding_style"
    })
    assert create_resp.status_code == 200
    assert create_resp.json()["status"] == "success"

    # List memories
    list_resp = client.get("/account/memory/?category=coding_style")
    assert list_resp.status_code == 200
    memories = list_resp.json()["memories"]
    assert len(memories) >= 1
    mem_id = memories[0]["id"]
    print("[OK] Memory creation and filtered listing verified.")

    # Delete single memory
    del_resp = client.post(f"/account/memory/{mem_id}/delete/")
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "success"

    # Clear all memories
    UserFact.objects.create(user=user, fact="Fact 1", category="general")
    UserFact.objects.create(user=user, fact="Fact 2", category="preference")
    clear_resp = client.post("/account/memory/clear/")
    assert clear_resp.status_code == 200
    assert clear_resp.json()["status"] == "success"
    assert UserFact.objects.filter(user=user).count() == 0
    print("[OK] Memory deletion and clear-all operations verified.")

    # 4. Agent Token Regeneration
    old_token = profile.get_or_create_agent_token()
    regen_resp = client.post("/api/agent/token/regenerate/")
    assert regen_resp.status_code == 200
    new_token = regen_resp.json()["agent_token"]
    assert new_token != old_token
    profile.refresh_from_db()
    assert profile.agent_token == new_token
    print("[OK] Desktop Agent token regeneration verified.")

if __name__ == "__main__":
    test_settings_redesign()
    print("\nALL SETTINGS REDESIGN CHECKS PASSED SUCCESSFULLY!")
