import os
import sys
import django

sys.path.insert(0, r"d:\dhruv\Simba_Intel - Copy")
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'simba_web.settings')
django.setup()

import unittest
import json
from django.contrib.auth.models import User
from django.test import RequestFactory

from chat.models import ChatSession, Message, UserProfile
from chat.views import message_info
from chat.services.conversation_memory import (
    build_conversation_context,
    build_context_messages,
    extract_conversation_facts,
    calculate_recent_turns_budget,
)
from chat.services.message_tree import append_turn, walk_active_chain


class TestMessageInfoAndLongContext(unittest.TestCase):

    def setUp(self):
        self.factory = RequestFactory()
        self.user, _ = User.objects.get_or_create(username="context_test_user")
        self.other_user, _ = User.objects.get_or_create(username="other_test_user")
        self.session = ChatSession.objects.create(user=self.user, title="Long Context Test Chat")
        self.other_session = ChatSession.objects.create(user=self.other_user, title="Other User Chat")

    def test_01_message_info_endpoint_metadata(self):
        # Create a user + assistant turn with stats metadata
        u_node, a_node = append_turn(
            self.session,
            "Explain quantum encryption",
            "Quantum encryption leverages photon polarization properties.",
            assistant_extra_data={
                "model": "quantum-core",
                "provider": "nvidia",
                "stats": {
                    "provider": "NVIDIA NIM",
                    "actual_model": "nvidia/nemotron-3-super-120b-a12b",
                    "input_tokens": 120,
                    "output_tokens": 450,
                    "total_tokens": 570,
                    "response_time_s": 1.45,
                    "ttft_s": 0.32,
                    "streaming": True,
                }
            },
            latency=1.45
        )

        request = self.factory.get(f"/messages/{a_node.id}/info/")
        request.user = self.user

        response = message_info(request, message_id=a_node.id)
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.content.decode("utf-8"))
        self.assertEqual(data["status"], "success")
        self.assertTrue(data["has_stats"])
        
        stats = data["stats"]
        self.assertEqual(stats["message_id"], a_node.id)
        self.assertEqual(stats["session_id"], self.session.id)
        self.assertEqual(stats["provider"], "NVIDIA NIM")
        self.assertEqual(stats["actual_model"], "nvidia/nemotron-3-super-120b-a12b")
        self.assertEqual(stats["input_tokens"], 120)
        self.assertEqual(stats["output_tokens"], 450)
        self.assertEqual(stats["total_tokens"], 570)
        self.assertEqual(stats["response_time_s"], 1.45)
        self.assertEqual(stats["ttft_s"], 0.32)
        self.assertTrue(stats["streaming"])
        self.assertGreater(stats["content_length"], 10)

        # Cross-user authorization check: other user must not access this message info
        request_other = self.factory.get(f"/messages/{a_node.id}/info/")
        request_other.user = self.other_user
        from django.http import Http404
        with self.assertRaises(Http404):
            message_info(request_other, message_id=a_node.id)

    def test_02_long_conversation_memory_and_fact_retention(self):
        """Simulate a 25-turn conversation and ensure early facts are preserved in context."""
        facts_turns = [
            ("My project is called Simba Intel.", "Got it, I've noted that your project is named Simba Intel."),
            ("I use Django for the backend.", "Django is an excellent choice for a robust web framework."),
            ("The frontend uses HTML/CSS/JavaScript with glassmorphic aesthetics.", "Great, vanilla web technologies with modern CSS provide great control."),
            ("The desktop agent runs on Windows.", "Understood, Windows desktop integration is registered."),
            ("Always prioritize Ox Alpha for complex reasoning.", "Noted, Ox Alpha will be the prioritized model for complex tasks."),
        ]

        # 1. Add early critical fact turns
        for user_q, ai_r in facts_turns:
            append_turn(self.session, user_q, ai_r)

        # 2. Add 20 intermediate technical turns (pushing the conversation past 25 turns)
        for i in range(1, 21):
            append_turn(
                self.session,
                f"Topic {i}: How do we optimize database queries for section {i}?",
                f"For section {i}, use select_related and prefetch_related to eliminate N+1 query overhead."
            )

        # Total message nodes = (5 + 20) * 2 = 50 nodes
        chain = walk_active_chain(self.session)
        self.assertEqual(len(chain), 50, "Full conversation must remain 100% persisted in database")

        # 3. Build context for a follow-up query after 25 turns
        context = build_conversation_context(
            self.session,
            user_query="Can you summarize my project name, backend stack, agent OS, and preferred model?",
            system_prompt="You are Simba, an AI assistant.",
            model_id="ox-alpha",
        )

        # Check context layers
        context_text = " ".join([m["content"] for m in context])

        # Verify key early facts exist in the context payload
        self.assertIn("Simba Intel", context_text, "Project name must be retained in context")
        self.assertIn("Django", context_text, "Backend framework must be retained in context")
        self.assertIn("Windows", context_text, "OS environment must be retained in context")
        self.assertIn("Ox Alpha", context_text, "Model preference directive must be retained in context")

        # Verify system layers
        system_messages = [m for m in context if m["role"] == "system"]
        self.assertGreaterEqual(len(system_messages), 2, "Must contain base system prompt and facts/summary blocks")

        # Verify active user query is the final turn
        self.assertEqual(context[-1]["role"], "user")
        self.assertIn("Can you summarize my project name", context[-1]["content"])

    def test_03_session_isolation_no_memory_leakage(self):
        """Verify that facts from Session A are NEVER leaked into Session B."""
        # Add facts to Session A
        append_turn(self.session, "My project is called ProjectAlphaX.", "Noted ProjectAlphaX.")
        append_turn(self.session, "We use FastAPI on Linux.", "Noted FastAPI and Linux.")

        # Add different facts to Session B
        append_turn(self.other_session, "My project is called BetaShield.", "Noted BetaShield.")

        # Build context for Session B
        ctx_b = build_conversation_context(
            self.other_session,
            user_query="What is my project?",
            system_prompt="You are Simba.",
            model_id="nova-mind"
        )
        ctx_b_text = " ".join([m["content"] for m in ctx_b])

        # Session B must know BetaShield
        self.assertIn("BetaShield", ctx_b_text)
        # Session B must NEVER know ProjectAlphaX or FastAPI from Session A
        self.assertNotIn("ProjectAlphaX", ctx_b_text, "Session A fact leaked into Session B!")
        self.assertNotIn("FastAPI", ctx_b_text, "Session A fact leaked into Session B!")

    def test_04_model_aware_budgeting(self):
        """Verify that larger context models get more recent verbatim turns than smaller ones."""
        chain_mock = [1] * 60 # 30 turns

        budget_large = calculate_recent_turns_budget("ox-alpha", chain_mock)
        budget_small = calculate_recent_turns_budget("sky-net-mini", chain_mock)
        budget_image = calculate_recent_turns_budget("image-studio", chain_mock)

        self.assertGreater(budget_large, budget_small, "Large context models should get more verbatim turns")
        self.assertGreaterEqual(budget_small, budget_image)

    def test_05_refresh_and_restoration_from_db(self):
        """Verify that refreshing/reloading from DB maintains the context without frontend reliance."""
        # Re-fetch session from DB
        fresh_session = ChatSession.objects.get(id=self.session.id)
        
        ctx = build_conversation_context(
            fresh_session,
            user_query="Continue the project.",
            system_prompt="You are Simba.",
            model_id="cyber-max"
        )
        
        self.assertTrue(len(ctx) > 0)
        self.assertEqual(ctx[0]["role"], "system")
        self.assertEqual(ctx[-1]["role"], "user")


if __name__ == '__main__':
    unittest.main()
