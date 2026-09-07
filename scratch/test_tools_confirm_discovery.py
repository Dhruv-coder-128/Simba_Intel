import os
import sys
import json
import django

sys.path.insert(0, os.path.abspath('.'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'simba_web.settings_sqlite_export')
django.setup()

from django.test import Client
from django.contrib.auth.models import User
from django.urls import reverse
from chat.agent.task_manager import default_task_manager, TaskStatus

def test_endpoints():
    print("=== Testing Agent Discovery, Confirmation, and Filter Endpoints ===")
    user = User.objects.filter(is_superuser=True).first() or User.objects.first()
    client = Client()
    client.force_login(user)

    # 1. Test /api/agent/tools/
    print("\n[1] Testing GET /api/agent/tools/ (Action Discovery Endpoint)...")
    res = client.get("/api/agent/tools/")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    data = res.json()
    assert data["status"] == "ok"
    assert "tools" in data
    assert "desktop_online" in data
    tools = data["tools"]
    assert len(tools) >= 10, f"Expected at least 10 tools, found {len(tools)}"
    
    # Check tool metadata fields
    first_tool = tools[0]
    for field in ["id", "display_name", "icon", "category", "execution_target", "risk_level", "requires_confirmation", "example_prompt"]:
        assert field in first_tool, f"Missing tool metadata field: {field}"
    print(f"  [OK] /api/agent/tools/ returned {len(tools)} tools with rich UI metadata!")

    # 2. Test /api/agent/task/confirm/
    print("\n[2] Testing POST /api/agent/task/confirm/ (Permission Gate Endpoint)...")
    # Create waiting task
    task = default_task_manager.create_task(title="Sensitive Delete File Task", user_id=user.id)
    default_task_manager.update_task_status(task.task_id, TaskStatus.WAITING_FOR_APPROVAL)

    # Test Allow
    res_allow = client.post(
        "/api/agent/task/confirm/",
        data=json.dumps({"task_id": task.task_id, "action": "allow"}),
        content_type="application/json"
    )
    assert res_allow.status_code == 200
    assert res_allow.json()["approved"] is True
    t_allowed = default_task_manager.get_task(task.task_id)
    assert t_allowed.status == TaskStatus.EXECUTING
    print("  [OK] Approve task succeeded: transitioned to EXECUTING")

    # Create another waiting task and test Cancel
    task2 = default_task_manager.create_task(title="Dangerous Script Task", user_id=user.id)
    default_task_manager.update_task_status(task2.task_id, TaskStatus.WAITING_FOR_APPROVAL)
    res_cancel = client.post(
        "/api/agent/task/confirm/",
        data=json.dumps({"task_id": task2.task_id, "action": "cancel"}),
        content_type="application/json"
    )
    assert res_cancel.status_code == 200
    assert res_cancel.json()["cancelled"] is True
    t_cancelled = default_task_manager.get_task(task2.task_id)
    assert t_cancelled.status == TaskStatus.CANCELLED
    print("  [OK] Cancel task succeeded: transitioned to CANCELLED")

    # 3. Test /agent/confirm/ (Direct Tool Confirmation)
    print("\n[3] Testing POST /agent/confirm/ (Direct Tool Confirmation Endpoint)...")
    res_direct = client.post("/agent/confirm/", {
        "tool_name": "calculator",
        "args": json.dumps({"expression": "100 * 5 + 20"})
    })
    assert res_direct.status_code == 200
    direct_data = res_direct.json()
    assert direct_data["success"] is True
    assert "520" in direct_data["output"]
    print(f"  [OK] Direct execution output: {direct_data['output']}")

    # 4. Test Task History Search & Status Filter
    print("\n[4] Testing /api/agent/task/history/ with search & status filters...")
    # Search filter
    res_search = client.get("/api/agent/task/history/?search=Sensitive")
    assert res_search.status_code == 200
    search_tasks = res_search.json()["tasks"]
    assert len(search_tasks) >= 1
    assert any("Sensitive" in t["title"] for t in search_tasks)
    print(f"  [OK] Search query 'Sensitive' matched {len(search_tasks)} task(s)")

    # Status filter
    res_status = client.get("/api/agent/task/history/?status=cancelled")
    assert res_status.status_code == 200
    status_tasks = res_status.json()["tasks"]
    assert len(status_tasks) >= 1
    assert all("CANCEL" in (t["status"] or "").upper() for t in status_tasks)
    print(f"  [OK] Status filter 'cancelled' matched {len(status_tasks)} task(s)")

    print("\n============================================================")
    print("ALL DISCOVERY, CONFIRMATION & FILTER TESTS PASSED (4/4)!")
    print("============================================================")

if __name__ == "__main__":
    test_endpoints()
