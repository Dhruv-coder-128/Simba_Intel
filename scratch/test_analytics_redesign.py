import os
import sys
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "simba_web.settings")
django.setup()

from django.test import RequestFactory
from django.urls import reverse
from django.contrib.auth import get_user_model
from chat.models import UsageEvent, ChatSession, Message
from chat.views import analytics_dashboard, analytics_data_api, analytics_export

User = get_user_model()

def test_analytics_redesign():
    print("Testing Complete Analytics Page Premium Redesign...")
    rf = RequestFactory()
    user, _ = User.objects.get_or_create(username="analytics_user", defaults={"email": "analytics@example.com"})
    user.set_password("pass1234")
    user.save()

    # 1. Clean empty state test
    UsageEvent.objects.filter(user=user).delete()
    ChatSession.objects.filter(user=user).delete()

    req_empty = rf.get(reverse("analytics_dashboard"))
    req_empty.user = user
    resp_empty = analytics_dashboard(req_empty)
    assert resp_empty.status_code == 200, f"Expected 200, got {resp_empty.status_code}"
    html_empty = resp_empty.content.decode("utf-8")
    assert "No usage recorded yet" in html_empty
    print("[OK] Empty state renders cleanly without errors.")

    # 2. Populate real data
    session1 = ChatSession.objects.create(user=user, title="Deep Quantum Analysis")
    session2 = ChatSession.objects.create(user=user, title="Neural Network Tuning")
    Message.objects.create(session=session1, role="user", content="Explain qubits")
    Message.objects.create(session=session1, role="assistant", content="Qubits represent superpositions.")
    Message.objects.create(session=session2, role="user", content="Optimize SGD")
    Message.objects.create(session=session2, role="assistant", content="Use AdamW optimizer with cosine warmup.")

    UsageEvent.objects.create(
        user=user, session=session1, provider="groq", model_id="llama-3.3-70b",
        event_type="chat", prompt_tokens=25, completion_tokens=150,
        estimated_cost_usd="0.001200", latency=1.45, success=True
    )
    UsageEvent.objects.create(
        user=user, session=session2, provider="mistral", model_id="mistral-large",
        event_type="chat", prompt_tokens=40, completion_tokens=220,
        estimated_cost_usd="0.003500", latency=2.10, success=True
    )
    UsageEvent.objects.create(
        user=user, session=session1, provider="groq", model_id="llama-3.3-70b",
        event_type="chat", prompt_tokens=15, completion_tokens=0,
        estimated_cost_usd="0.000100", latency=0.5, success=False
    )
    UsageEvent.objects.create(
        user=user, session=session1, provider="pollinations", model_id="flux-schnell",
        event_type="image", prompt_tokens=0, completion_tokens=0,
        estimated_cost_usd="0.000000", latency=3.2, success=True
    )

    # 3. Main Dashboard View Verification
    req = rf.get(reverse("analytics_dashboard"))
    req.user = user
    resp = analytics_dashboard(req)
    assert resp.status_code == 200

    html = resp.content.decode("utf-8")
    assert "USAGE ANALYTICS" in html
    assert "LIVE TELEMETRY" in html
    assert 'id="requestsChart"' in html
    assert 'id="tokensChart"' in html
    assert 'id="histogramChart"' in html
    assert 'id="modelStackChart"' in html
    assert 'id="typeChart"' in html
    assert 'id="heatmapGrid"' in html
    assert 'Deep Quantum Analysis' in html
    print("[OK] Dashboard HTML & Context verified with rich real metrics.")

    # 4. JSON Data API endpoint verification across ranges
    for r in ["today", "7d", "30d", "all"]:
        req_api = rf.get(f"{reverse('analytics_data_api')}?range={r}")
        req_api.user = user
        api_resp = analytics_data_api(req_api)
        assert api_resp.status_code == 200, f"API failed for range {r}"
        data = json.loads(api_resp.content.decode("utf-8"))
        assert "total_requests" in data
        assert "daily_series" in data
        assert "by_model" in data
        assert "recent_events" in data
        assert data["total_requests"] == 3
        print(f"[OK] Analytics Data API range '{r}' returned valid payload.")

    # 5. Export Endpoint Verification
    req_csv = rf.get(f"{reverse('analytics_export')}?format=csv")
    req_csv.user = user
    csv_resp = analytics_export(req_csv)
    assert csv_resp.status_code == 200
    assert "text/csv" in csv_resp["Content-Type"]
    assert "attachment; filename=\"simba_analytics.csv\"" in csv_resp["Content-Disposition"]
    assert b"Timestamp,Event Type,Model ID" in csv_resp.content
    print("[OK] CSV Export verified.")

    req_json = rf.get(f"{reverse('analytics_export')}?format=json")
    req_json.user = user
    json_resp = analytics_export(req_json)
    assert json_resp.status_code == 200
    assert "application/json" in json_resp["Content-Type"]
    assert "attachment; filename=\"simba_analytics.json\"" in json_resp["Content-Disposition"]
    parsed_json = json.loads(json_resp.content)
    assert len(parsed_json) == 4
    print("[OK] JSON Export verified.")

if __name__ == "__main__":
    test_analytics_redesign()
    print("\nALL ANALYTICS REDESIGN TESTS PASSED SUCCESSFULLY!")
