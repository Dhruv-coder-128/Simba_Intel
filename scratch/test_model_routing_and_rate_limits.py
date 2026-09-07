import os
import sys
import django

# Add project root to sys.path
sys.path.insert(0, r"d:\dhruv\Simba_Intel - Copy")
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'simba_web.settings')
django.setup()

import unittest
from unittest.mock import patch, MagicMock
from django.contrib.auth.models import User
from django.test import RequestFactory

from chat.services.model_registry import MODEL_REGISTRY, get_model_config
from chat.services.provider_manager import get_provider
from chat.services.smart_router import route_with_reason, _is_model_healthy
from chat.services.ai_router import (
    is_provider_cooling_down,
    mark_provider_cooldown,
    clear_provider_cooldown,
    is_rate_limit_error,
    extract_retry_after,
)
from chat.services.error_types import normalize_provider_error, AIErrorType
from chat.services.usage import check_daily_limit
from chat.models import UserProfile, UsageEvent


class TestModelRoutingAndRateLimits(unittest.TestCase):

    def setUp(self):
        # Clear any leftover cooldowns before each test
        for p in ["groq", "mistral", "nvidia", "openrouter", "virtual", "pollinations"]:
            clear_provider_cooldown(p)

    def test_01_model_registry_and_providers_mapping(self):
        expected_mappings = {
            "cyber-max": ("virtual", "cyber-max-pool"),
            "nova-mind": ("groq", "groq/compound-mini"),
            "sky-net": ("mistral", "mistral-large-latest"),
            "sky-net-mini": ("mistral", "mistral-medium-3-5"),
            "quantum-core": ("nvidia", "quantum-core-pool"),
            "ox-alpha": ("openrouter", "nvidia/nemotron-3-super-120b-a12b:free"),
            "image-studio": ("pollinations", "flux"),
        }

        for model_id, (expected_provider, expected_actual) in expected_mappings.items():
            self.assertIn(model_id, MODEL_REGISTRY, f"Model {model_id} missing in registry")
            cfg = get_model_config(model_id)
            self.assertEqual(cfg.provider, expected_provider, f"Mismatch provider for {model_id}")
            self.assertEqual(cfg.actual_model, expected_actual, f"Mismatch actual_model for {model_id}")

            # Verify provider adapter can be loaded
            if expected_provider != "pollinations":
                provider_obj = get_provider(expected_provider)
                self.assertIsNotNone(provider_obj, f"Failed to instantiate provider {expected_provider}")

    def test_02_manual_model_selection_overrides_auto(self):
        models_to_test = ["cyber-max", "nova-mind", "sky-net", "quantum-core", "ox-alpha"]
        for m in models_to_test:
            resolved_id, mode, reason = route_with_reason(m, "Write a complex Python script", False)
            self.assertEqual(resolved_id, m, f"Manual selection {m} was altered")
            self.assertEqual(mode, "manual", f"Mode should be manual for {m}")
            self.assertIn("Manual Override", reason)

    def test_03_provider_rate_limit_isolation(self):
        # Simulate a 429 on Groq
        mark_provider_cooldown("groq", seconds=60)

        # Groq must be in cooldown
        self.assertTrue(is_provider_cooling_down("groq"))

        # Unrelated providers MUST NOT be in cooldown
        self.assertFalse(is_provider_cooling_down("mistral"), "Mistral should remain active")
        self.assertFalse(is_provider_cooling_down("nvidia"), "NVIDIA should remain active")
        self.assertFalse(is_provider_cooling_down("openrouter"), "OpenRouter should remain active")

        # Models backed by Mistral, NVIDIA, and OpenRouter must report healthy
        self.assertTrue(_is_model_healthy("sky-net"))
        self.assertTrue(_is_model_healthy("quantum-core"))
        self.assertTrue(_is_model_healthy("ox-alpha"))

        # Nova mind (backed by Groq) must report cooling down
        self.assertFalse(_is_model_healthy("nova-mind"))

    def test_04_auto_routing_bypasses_cooling_down_provider(self):
        # Put OpenRouter and Groq in cooldown
        mark_provider_cooldown("openrouter", seconds=60)
        mark_provider_cooldown("groq", seconds=60)

        # In auto mode, route_with_reason should pick a healthy candidate (e.g. quantum-core or sky-net-mini)
        resolved_id, mode, reason = route_with_reason("auto", "Solve this coding problem", False)
        self.assertEqual(mode, "auto")
        self.assertIn(resolved_id, ["quantum-core", "sky-net-mini", "cyber-max"])

    def test_05_check_daily_limit_staff_and_user_quota(self):
        # 1. Staff / Superuser accounts must bypass daily limit
        staff_user, _ = User.objects.get_or_create(username="test_staff_user", defaults={"is_staff": True})
        staff_user.is_staff = True
        staff_user.save()
        allowed, msg = check_daily_limit(staff_user, "chat")
        self.assertTrue(allowed)
        self.assertIsNone(msg)

        # 2. Regular user with unlimited_usage = True must bypass
        regular_user, _ = User.objects.get_or_create(username="test_regular_user_unlimited")
        profile = UserProfile.get_or_create_for(regular_user)
        profile.unlimited_usage = True
        profile.save()
        allowed, msg = check_daily_limit(regular_user, "chat", profile=profile)
        self.assertTrue(allowed)
        self.assertIsNone(msg)

        # 3. Standard user reaching limit must receive clear "Account daily token limit reached" message
        limited_user, _ = User.objects.get_or_create(username="test_limited_user")
        limited_user.is_staff = False
        limited_user.is_superuser = False
        limited_user.save()
        lim_profile = UserProfile.get_or_create_for(limited_user)
        lim_profile.unlimited_usage = False
        lim_profile.daily_token_limit = 1000
        lim_profile.save()

        # Create real usage events exceeding limit
        UsageEvent.objects.create(
            user=limited_user,
            event_type="chat",
            prompt_tokens=1500,
            completion_tokens=1500,
            success=True,
            provider="groq",
            model_id="nova-mind",
        )

        allowed, msg = check_daily_limit(limited_user, "chat", profile=lim_profile)
        self.assertFalse(allowed)
        self.assertIn("Account daily token limit reached", msg)
        self.assertNotIn("Provider Rate Limited", msg)

    def test_06_error_normalization(self):
        # 429
        e429 = Exception("Error code 429: Too Many Requests. Try again in 30s")
        norm429 = normalize_provider_error(e429, provider="groq", model_id="nova-mind")
        self.assertEqual(norm429.error_type, AIErrorType.RATE_LIMITED)
        self.assertEqual(norm429.status_code, 429)
        self.assertEqual(norm429.retry_after, 30)
        self.assertIn("Groq", norm429.message)

        # 401
        e401 = Exception("401 Unauthorized: Invalid API key")
        norm401 = normalize_provider_error(e401, provider="mistral", model_id="sky-net")
        self.assertEqual(norm401.error_type, AIErrorType.AUTH_ERROR)
        self.assertEqual(norm401.status_code, 401)

        # 404
        e404 = Exception("404 Model does not exist or has been decommissioned")
        norm404 = normalize_provider_error(e404, provider="nvidia", model_id="quantum-core")
        self.assertEqual(norm404.error_type, AIErrorType.MODEL_NOT_FOUND)
        self.assertEqual(norm404.status_code, 404)

        # Timeout
        e_time = TimeoutError("Request timed out after 15.0s")
        norm_time = normalize_provider_error(e_time, provider="openrouter", model_id="ox-alpha")
        self.assertEqual(norm_time.error_type, AIErrorType.TIMEOUT)
        self.assertEqual(norm_time.status_code, 504)


if __name__ == '__main__':
    unittest.main()
