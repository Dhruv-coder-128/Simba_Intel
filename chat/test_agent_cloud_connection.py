"""Automated Test Suite for Cloud ↔ Local Desktop Agent Connection (Phase 1).
Tests authentication, long-poll dispatch, result ingestion, offline guards, and user isolation.
"""
import json
import threading
import time
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse

from chat.models import UserProfile
from chat.agent.agent_hub import default_agent_hub, DesktopAgentConnection
from chat.agent.controller import default_agent_controller
from chat.agent.executor import default_executor

User = get_user_model()


class DesktopAgentCloudConnectionTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        # Create primary test user
        self.user = User.objects.create_user(
            username="test_dhruv",
            email="dhruv@example.com",
            password="SecurePassword123!",
        )
        self.profile, _ = UserProfile.objects.get_or_create(user=self.user)
        self.token = self.profile.get_or_create_agent_token()

        # Create secondary test user for multi-tenant isolation testing
        self.user2 = User.objects.create_user(
            username="other_user",
            email="other@example.com",
            password="SecurePassword123!",
        )
        self.profile2, _ = UserProfile.objects.get_or_create(user=self.user2)
        self.token2 = self.profile2.get_or_create_agent_token()

    def tearDown(self):
        default_agent_hub.disconnect_agent(self.user.id)
        default_agent_hub.disconnect_agent(self.user2.id)

    def test_01_agent_connect_requires_valid_token(self):
        """Rejects unauthenticated or invalid token connect requests."""
        # Missing token
        res = self.client.post(
            reverse("agent_connect"),
            data=json.dumps({"hostname": "DESKTOP-TEST"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 401)

        # Invalid token
        res = self.client.post(
            reverse("agent_connect"),
            data=json.dumps({"hostname": "DESKTOP-TEST"}),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer invalid_token_12345",
        )
        self.assertEqual(res.status_code, 401)

    def test_02_agent_connect_and_status_success(self):
        """Successfully authenticates and connects Desktop Agent."""
        res = self.client.post(
            reverse("agent_connect"),
            data=json.dumps({
                "agent_id": "win_agent_01",
                "hostname": "DESKTOP-WIN11",
                "platform": "Windows 11 (build 26100)",
                "agent_version": "1.0.0",
            }),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["user_id"], self.user.id)
        self.assertEqual(data["username"], "test_dhruv")
        self.assertTrue(default_agent_hub.is_user_agent_online(self.user.id))

        # Check frontend status endpoint
        self.client.force_login(self.user)
        status_res = self.client.get(reverse("agent_status"))
        self.assertEqual(status_res.status_code, 200)
        status_data = status_res.json()
        self.assertTrue(status_data["connected"])
        self.assertEqual(status_data["status"], "online")
        self.assertEqual(status_data["device"]["hostname"], "DESKTOP-WIN11")

    def test_03_heartbeat_and_disconnect(self):
        """Maintains heartbeat and handles graceful disconnect."""
        # Connect
        self.client.post(
            reverse("agent_connect"),
            data=json.dumps({"agent_id": "win_agent_01", "hostname": "DESKTOP-WIN11"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )
        self.assertTrue(default_agent_hub.is_user_agent_online(self.user.id))

        # Heartbeat
        hb_res = self.client.post(
            reverse("agent_heartbeat"),
            data=json.dumps({"agent_id": "win_agent_01"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )
        self.assertEqual(hb_res.status_code, 200)

        # Disconnect
        dc_res = self.client.post(
            reverse("agent_disconnect"),
            data=json.dumps({"agent_id": "win_agent_01"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )
        self.assertEqual(dc_res.status_code, 200)
        self.assertFalse(default_agent_hub.is_user_agent_online(self.user.id))

    def test_04_command_poll_and_result_lifecycle(self):
        """Dispatches command to agent, polls it, submits result, and verifies completion."""
        # Connect agent
        self.client.post(
            reverse("agent_connect"),
            data=json.dumps({"agent_id": "win_agent_01", "hostname": "DESKTOP-WIN11"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )

        # Background thread to simulate synchronous dispatch
        result_holder = {}

        def _dispatch_worker():
            res = default_agent_hub.dispatch_command_and_wait(
                user_id=self.user.id,
                tool="open_application",
                arguments={"application": "notepad"},
                timeout=5.0,
            )
            result_holder["result"] = res

        dispatch_thread = threading.Thread(target=_dispatch_worker)
        dispatch_thread.start()

        # Agent polls for commands
        time.sleep(0.1)
        poll_res = self.client.post(
            reverse("agent_poll"),
            data=json.dumps({"agent_id": "win_agent_01", "timeout": 2.0}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )
        self.assertEqual(poll_res.status_code, 200)
        poll_data = poll_res.json()
        self.assertEqual(len(poll_data["commands"]), 1)
        command = poll_data["commands"][0]
        self.assertEqual(command["tool"], "open_application")
        self.assertEqual(command["arguments"]["application"], "notepad")

        # Agent submits verified result
        cmd_id = command["command_id"]
        result_res = self.client.post(
            reverse("agent_result"),
            data=json.dumps({
                "command_id": cmd_id,
                "tool": "open_application",
                "action": "open_application",
                "target": "Notepad",
                "success": True,
                "output": "Notepad opened and focused.",
                "details": {"hwnd": 12345, "pid": 6789},
            }),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )
        self.assertEqual(result_res.status_code, 200)

        dispatch_thread.join(timeout=3.0)
        self.assertIn("result", result_holder)
        exec_res = result_holder["result"]
        self.assertTrue(exec_res.success)
        self.assertEqual(exec_res.output, "Notepad opened and focused.")
        self.assertEqual(exec_res.details["hwnd"], 12345)

    def test_05_multi_tenant_user_isolation(self):
        """Confirms User A cannot receive or answer commands meant for User B."""
        # Connect both User 1 and User 2 agents
        self.client.post(
            reverse("agent_connect"),
            data=json.dumps({"agent_id": "agent_u1", "hostname": "PC-USER1"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )
        self.client.post(
            reverse("agent_connect"),
            data=json.dumps({"agent_id": "agent_u2", "hostname": "PC-USER2"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token2}",
        )

        # Dispatch command meant for User 1
        dispatch_thread = threading.Thread(
            target=lambda: default_agent_hub.dispatch_command_and_wait(
                user_id=self.user.id,
                tool="open_application",
                arguments={"application": "calc"},
                timeout=2.0,
            )
        )
        dispatch_thread.start()
        time.sleep(0.1)

        # User 2 polls -> should receive 0 commands
        poll_res_u2 = self.client.post(
            reverse("agent_poll"),
            data=json.dumps({"agent_id": "agent_u2", "timeout": 0.5}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token2}",
        )
        self.assertEqual(poll_res_u2.status_code, 200)
        self.assertEqual(len(poll_res_u2.json()["commands"]), 0)

        # User 1 polls -> receives the command
        poll_res_u1 = self.client.post(
            reverse("agent_poll"),
            data=json.dumps({"agent_id": "agent_u1", "timeout": 0.5}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )
        self.assertEqual(poll_res_u1.status_code, 200)
        self.assertEqual(len(poll_res_u1.json()["commands"]), 1)

        dispatch_thread.join(timeout=3.0)

    def test_06_regenerate_token_invalidates_session(self):
        """Regenerating agent token changes the token and marks previous session offline."""
        # Connect
        self.client.post(
            reverse("agent_connect"),
            data=json.dumps({"agent_id": "win_agent_01", "hostname": "DESKTOP-WIN11"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )
        self.assertTrue(default_agent_hub.is_user_agent_online(self.user.id))

        # Regenerate token via web endpoint
        self.client.force_login(self.user)
        regen_res = self.client.post(reverse("agent_regenerate_token"))
        self.assertEqual(regen_res.status_code, 200)
        new_token = regen_res.json()["agent_token"]
        self.assertNotEqual(new_token, self.token)
        self.assertFalse(default_agent_hub.is_user_agent_online(self.user.id))

        # Old token can no longer authenticate
        old_poll = self.client.post(
            reverse("agent_poll"),
            data=json.dumps({"agent_id": "win_agent_01"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )
        self.assertEqual(old_poll.status_code, 401)
