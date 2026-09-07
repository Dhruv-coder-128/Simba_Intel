"""Full Integration Verification Script for SIMBA_INTEL Agent Mode, Voice Agent, and Task History.
Tests:
1. Cloud Tool Execution (calculator, search_web) - executes safely without desktop agent.
2. Desktop Tool Offline Guard (open_application) - truthful failure with 'python simba_agent.py' instructions.
3. Desktop Tool Online Dispatch - executes successfully when desktop agent is connected.
4. AgentTaskManager Lifecycle - state transitions (PLANNING, WAITING, EXECUTING, VERIFYING, COMPLETED, CANCELLED).
5. Agent Task Cancel & History Endpoints (/api/agent/task/cancel/, /api/agent/task/history/).
6. Session Mode Views - assistant, agent, voice rendering with proper context variables and DOM stations.
"""
import os
import sys
import json
import threading
import time

sys.path.insert(0, os.path.abspath('.'))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'simba_web.settings_sqlite_export')

import django
django.setup()

from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from chat.models import UserProfile
from chat.agent.agent_hub import default_agent_hub
from chat.agent.executor import default_executor
from chat.agent.task_manager import default_task_manager, TaskStatus

User = get_user_model()

def run_tests():
    print("=" * 60)
    print("SIMBA_INTEL AGENT MODE, VOICE AGENT & TASK HISTORY VERIFICATION")
    print("=" * 60)
    
    # Setup test user
    user, _ = User.objects.get_or_create(username="verify_user", defaults={"email": "verify@example.com"})
    user.set_password("VerifyPass123!")
    user.save()
    profile, _ = UserProfile.objects.get_or_create(user=user)
    token = profile.get_or_create_agent_token()
    
    client = Client()
    client.force_login(user)

    # ----------------------------------------------------
    # 1. Cloud Tool Execution
    # ----------------------------------------------------
    print("\n[1/6] Testing Cloud Tool Execution (calculator, search_web)...")
    res_calc = default_executor.execute_tool(
        tool_name="calculator",
        args={"expression": "25 * 4 + 10"},
        user_id=user.id
    )
    assert res_calc.success is True, f"Calculator failed: {res_calc.error}"
    assert "110" in str(res_calc.output), f"Unexpected calc output: {res_calc.output}"
    print(f"  [OK] Calculator executed without desktop agent: {res_calc.output.strip()}")

    res_search = default_executor.execute_tool(
        tool_name="search_web",
        args={"query": "test query"},
        user_id=user.id
    )
    assert res_search.execution_target == "cloud", f"search_web execution_target should be cloud, got {res_search.execution_target}"
    print(f"  [OK] search_web routed to cloud executor (success={res_search.success})")

    # ----------------------------------------------------
    # 2. Desktop Tool Offline Guard
    # ----------------------------------------------------
    print("\n[2/6] Testing Desktop Tool Offline Guard...")
    default_agent_hub.disconnect_agent(user.id)
    res_offline = default_executor.execute_tool(
        tool_name="open_application",
        args={"app_name": "notepad"},
        user_id=user.id
    )
    assert res_offline.success is False, "Desktop tool should fail when PC is offline"
    assert "simba_agent.py" in str(res_offline.error), f"Error message should mention simba_agent.py: {res_offline.error}"
    print(f"  [OK] Truthful offline rejection with instructions: {res_offline.error[:80]}...")

    # ----------------------------------------------------
    # 3. Desktop Tool Online Dispatch
    # ----------------------------------------------------
    print("\n[3/6] Testing Desktop Tool Online Dispatch...")
    default_agent_hub.register_agent(
        user=user,
        agent_id="mock_pc_01",
        hostname="VERIFY-PC",
        platform_str="Windows 11",
        agent_version="1.0.0"
    )
    assert default_agent_hub.is_user_agent_online(user.id) is True

    def agent_worker():
        for _ in range(50):
            cmds = default_agent_hub.poll_commands(user.id, agent_id="mock_pc_01", timeout=0.2)
            if cmds:
                for cmd in cmds:
                    default_agent_hub.submit_result(
                        user_id=user.id,
                        command_id=cmd["command_id"],
                        result_dict={
                            "success": True,
                            "output": f"Executed {cmd['tool']} on VERIFY-PC",
                            "error": None,
                        }
                    )
                break
            time.sleep(0.05)

    worker = threading.Thread(target=agent_worker, daemon=True)
    worker.start()

    res_online = default_executor.execute_tool(
        tool_name="open_application",
        args={"app_name": "notepad"},
        user_id=user.id
    )
    assert res_online.success is True, f"Expected online execution success, got: {res_online.error}"
    assert "Executed open_application" in res_online.output
    print(f"  [OK] Online desktop dispatch and response succeeded: {res_online.output}")

    # Clean up connection
    default_agent_hub.disconnect_agent(user.id)

    # ----------------------------------------------------
    # 4. AgentTaskManager Lifecycle
    # ----------------------------------------------------
    print("\n[4/6] Testing AgentTaskManager Lifecycle & State Transitions...")
    task = default_task_manager.create_task(
        title="Automated Test Workflow",
        user_id=user.id,
        steps=[
            {"tool": "read_file", "description": "Read log file"},
            {"tool": "search_web", "description": "Summarize findings"}
        ]
    )
    assert task.task_id is not None
    assert task.status == TaskStatus.PLANNING

    default_task_manager.update_task_status(task.task_id, TaskStatus.WAITING_FOR_APPROVAL)
    t_waiting = default_task_manager.get_task(task.task_id)
    assert t_waiting.status == TaskStatus.WAITING_FOR_APPROVAL

    default_task_manager.update_task_status(task.task_id, TaskStatus.EXECUTING)
    default_task_manager.update_step_status(task.task_id, step_index=1, status="in_progress")
    t_exec = default_task_manager.get_task(task.task_id)
    assert t_exec.status == TaskStatus.EXECUTING

    default_task_manager.update_task_status(task.task_id, TaskStatus.VERIFYING)
    default_task_manager.update_step_status(task.task_id, step_index=1, status="completed", verified=True)
    t_ver = default_task_manager.get_task(task.task_id)
    assert t_ver.status == TaskStatus.VERIFYING

    default_task_manager.complete_task(task.task_id, success=True, final_result="All steps verified.")
    t_done = default_task_manager.get_task(task.task_id)
    assert t_done.status == TaskStatus.COMPLETED
    assert t_done.completion_time is not None
    print("  [OK] Full lifecycle transitions validated (PLANNING -> WAITING -> EXECUTING -> VERIFYING -> COMPLETED)")

    # Test task cancellation
    task_to_cancel = default_task_manager.create_task(
        title="Long Running Task",
        user_id=user.id
    )
    success = default_task_manager.cancel_task(task_id=task_to_cancel.task_id, user_id=user.id)
    assert success is True
    t_cancelled = default_task_manager.get_task(task_to_cancel.task_id)
    assert t_cancelled.status == TaskStatus.CANCELLED
    print("  [OK] Task cancellation verified")

    # ----------------------------------------------------
    # 5. Agent Task Cancel & History Endpoints
    # ----------------------------------------------------
    print("\n[5/6] Testing Endpoints (/api/agent/task/cancel/ & /api/agent/task/history/)...")
    active_task = default_task_manager.create_task(
        title="Active API Task",
        user_id=user.id
    )
    default_task_manager.update_task_status(active_task.task_id, TaskStatus.EXECUTING)

    cancel_res = client.post(
        reverse("agent_task_cancel"),
        data=json.dumps({"task_id": active_task.task_id, "reason": "Abort"}),
        content_type="application/json"
    )
    assert cancel_res.status_code == 200, f"Cancel API returned {cancel_res.status_code}: {cancel_res.content}"
    cancel_data = cancel_res.json()
    assert cancel_data["status"] == "ok"
    assert cancel_data["cancelled"] is True
    print("  [OK] /api/agent/task/cancel/ successfully cancelled task")

    history_res = client.get(reverse("agent_task_history"))
    assert history_res.status_code == 200
    history_data = history_res.json()
    assert history_data["status"] == "ok"
    assert len(history_data["tasks"]) >= 2
    print(f"  [OK] /api/agent/task/history/ returned {len(history_data['tasks'])} user tasks")

    # ----------------------------------------------------
    # 6. Session Mode Views & DOM Elements
    # ----------------------------------------------------
    print("\n[6/6] Testing Session Mode Views & HTML Template...")
    
    # 6a. Agent Mode
    res_agent = client.get("/?type=agent")
    assert res_agent.status_code == 200, f"Failed to render type=agent: {res_agent.status_code}"
    html_agent = res_agent.content.decode("utf-8")
    assert 'id="agentWorkspace"' in html_agent, "agentWorkspace missing in agent mode"
    assert 'id="agentTaskHistoryDrawer"' in html_agent, "agentTaskHistoryDrawer missing in agent mode"
    assert 'id="agentHistoryOverlay"' in html_agent, "agentHistoryOverlay missing in agent mode"
    assert 'id="agentEmptyTaskCard"' in html_agent, "agentEmptyTaskCard missing in agent mode"
    assert 'id="agentActiveTaskCard"' in html_agent, "agentActiveTaskCard missing in agent mode"
    assert 'id="pcStatusChip"' in html_agent, "pcStatusChip missing in agent mode"
    assert 'id="pcAgentInstructionsModal"' in html_agent, "pcAgentInstructionsModal missing in agent mode"
    assert 'id="voiceWorkspace"' not in html_agent, "voiceWorkspace should NOT appear in agent mode"
    print("  [OK] Agent mode rendered with agentWorkspace, task history drawer, status cards & quick tasks")

    # 6b. Voice Mode
    res_voice = client.get("/?type=voice")
    assert res_voice.status_code == 200, f"Failed to render type=voice: {res_voice.status_code}"
    html_voice = res_voice.content.decode("utf-8")
    assert 'id="voiceWorkspace"' in html_voice, "voiceWorkspace missing in voice mode"
    assert 'id="voiceVisualizerContainer"' in html_voice, "voiceVisualizerContainer missing in voice mode"
    assert 'id="voiceMainMicBtn"' in html_voice, "voiceMainMicBtn missing in voice mode"
    assert 'id="voiceTranscriptCard"' in html_voice, "voiceTranscriptCard missing in voice mode"
    assert 'id="voiceResponseCard"' in html_voice, "voiceResponseCard missing in voice mode"
    assert 'id="agentWorkspace"' not in html_voice, "agentWorkspace should NOT appear in voice mode"
    assert 'id="agentTaskHistoryDrawer"' not in html_voice, "agentTaskHistoryDrawer MUST NOT appear in voice mode"
    print("  [OK] Voice mode rendered with voiceWorkspace, visualizer, mic & zero agent contamination")

    # 6c. Assistant Mode
    res_asst = client.get("/?type=assistant")
    assert res_asst.status_code == 200, f"Failed to render type=assistant: {res_asst.status_code}"
    html_asst = res_asst.content.decode("utf-8")
    assert 'id="agentWorkspace"' not in html_asst, "agentWorkspace should not appear in assistant mode"
    assert 'id="voiceWorkspace"' not in html_asst, "voiceWorkspace should not appear in assistant mode"
    assert 'id="agentTaskHistoryDrawer"' not in html_asst, "agentTaskHistoryDrawer MUST NOT appear in assistant mode"
    assert 'id="qcHome"' in html_asst, "qcHome must appear in assistant mode"
    print("  [OK] Assistant mode rendered clean without agent/voice operations bars or task history drawer")

    print("\n" + "=" * 60)
    print("ALL VERIFICATIONS PASSED SUCCESSFULLY (6/6)!")
    print("=" * 60)

if __name__ == "__main__":
    run_tests()
