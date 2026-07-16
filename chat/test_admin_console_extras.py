"""Tests for the enterprise admin-console upgrade: soft delete/restore,
data export, per-user usage limits, feature-flag enforcement across the
product (not just maintenance_mode), Broadcast scheduling, the new user-list
filters, and audit-log IP/browser capture + search. Kept separate from
chat/test_admin_console.py (the original console) since this is specifically
the delta from that upgrade."""
import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from chat.models import AdminAuditLog, Broadcast, FeatureFlag, UserProfile, UsageEvent, ChatSession
from chat.services.usage import check_daily_limit

User = get_user_model()


class SoftDeleteRestoreTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(username="admin", password="testpass123", email="admin@example.com")
        self.target = User.objects.create_user(username="target", password="testpass123", email="target@example.com")
        self.client.force_login(self.superuser)

    def test_delete_account_blocks_login_and_hides_from_default_list(self):
        self.client.post(reverse("admin_user_detail", args=[self.target.id]), {"action": "delete_account"})
        self.target.refresh_from_db()
        profile = UserProfile.objects.get(user=self.target)
        self.assertTrue(profile.is_deleted)
        self.assertFalse(self.target.is_active)

        response = self.client.get(reverse("admin_users_list"))
        self.assertNotContains(response, "target@example.com")

        response = self.client.get(reverse("admin_users_list") + "?status=deleted")
        self.assertContains(response, "target@example.com")

    def test_restore_account_reactivates_and_unhides(self):
        self.client.post(reverse("admin_user_detail", args=[self.target.id]), {"action": "delete_account"})
        self.client.post(reverse("admin_user_detail", args=[self.target.id]), {"action": "restore_account"})
        self.target.refresh_from_db()
        profile = UserProfile.objects.get(user=self.target)
        self.assertFalse(profile.is_deleted)
        self.assertTrue(self.target.is_active)

    def test_restore_does_not_lift_an_independent_ban(self):
        self.client.post(reverse("admin_user_detail", args=[self.target.id]), {"action": "ban", "reason": "spam"})
        self.client.post(reverse("admin_user_detail", args=[self.target.id]), {"action": "delete_account"})
        self.client.post(reverse("admin_user_detail", args=[self.target.id]), {"action": "restore_account"})
        self.target.refresh_from_db()
        profile = UserProfile.objects.get(user=self.target)
        self.assertFalse(profile.is_deleted)
        self.assertTrue(profile.is_banned)
        self.assertFalse(self.target.is_active)  # still banned, restore shouldn't reactivate login

    def test_user_without_profile_row_is_not_hidden_as_deleted(self):
        # Profile is created lazily - a brand new user has none yet, and
        # must still show up in the default (non-deleted) list.
        fresh = User.objects.create_user(username="fresh", password="testpass123", email="fresh@example.com")
        self.assertFalse(UserProfile.objects.filter(user=fresh).exists())
        response = self.client.get(reverse("admin_users_list"))
        self.assertContains(response, "fresh@example.com")


class ExportUserDataTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(username="admin", password="testpass123", email="admin@example.com")
        self.target = User.objects.create_user(username="target", password="testpass123", email="target@example.com")
        ChatSession.objects.create(user=self.target, title="Test Chat")
        self.client.force_login(self.superuser)

    def test_export_returns_valid_json_with_expected_keys(self):
        response = self.client.get(reverse("admin_export_user_data", args=[self.target.id]))
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertIn("account", data)
        self.assertIn("profile", data)
        self.assertIn("usage_summary", data)
        self.assertIn("chat_sessions", data)
        self.assertEqual(data["account"]["email"], "target@example.com")
        self.assertEqual(len(data["chat_sessions"]), 1)

    def test_export_is_audit_logged(self):
        self.client.get(reverse("admin_export_user_data", args=[self.target.id]))
        self.assertTrue(AdminAuditLog.objects.filter(action="export_user_data", target_user=self.target).exists())


class UsageLimitTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="capped", password="testpass123", email="capped@example.com")
        self.profile = UserProfile.objects.create(user=self.user, daily_chat_limit=2)

    def test_blocked_once_daily_limit_reached(self):
        for _ in range(2):
            UsageEvent.objects.create(user=self.user, provider="groq", model_id="cyber-max", event_type="chat")
        allowed, reason = check_daily_limit(self.user, "chat")
        self.assertFalse(allowed)
        self.assertIn("Daily limit reached", reason)

    def test_allowed_under_the_limit(self):
        UsageEvent.objects.create(user=self.user, provider="groq", model_id="cyber-max", event_type="chat")
        allowed, reason = check_daily_limit(self.user, "chat")
        self.assertTrue(allowed)
        self.assertIsNone(reason)

    def test_unlimited_bypasses_the_cap_entirely(self):
        self.profile.unlimited_usage = True
        self.profile.save(update_fields=["unlimited_usage"])
        for _ in range(10):
            UsageEvent.objects.create(user=self.user, provider="groq", model_id="cyber-max", event_type="chat")
        allowed, reason = check_daily_limit(self.user, "chat")
        self.assertTrue(allowed)

    def test_yesterdays_usage_does_not_count_toward_todays_limit(self):
        old = UsageEvent.objects.create(user=self.user, provider="groq", model_id="cyber-max", event_type="chat")
        old.created_at = timezone.now() - timedelta(days=1)
        old.save(update_fields=["created_at"])
        allowed, _ = check_daily_limit(self.user, "chat")
        self.assertTrue(allowed)

    def test_admin_can_update_limits(self):
        superuser = User.objects.create_superuser(username="admin2", password="testpass123", email="admin2@example.com")
        client = Client()
        client.force_login(superuser)
        client.post(reverse("admin_user_detail", args=[self.user.id]), {
            "action": "update_usage_limits",
            "daily_chat_limit": "5",
            "daily_image_limit": "3",
            "daily_vision_limit": "3",
            "daily_token_limit": "50000",
        })
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.daily_chat_limit, 5)
        self.assertFalse(self.profile.unlimited_usage)


class FeatureFlagEnforcementTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="flaguser", password="testpass123", email="flaguser@example.com")
        self.client.force_login(self.user)

    def _disable(self, key):
        # save(), not queryset.update() - the cache invalidation in
        # FeatureFlag.save() only fires on an actual instance save (which is
        # what the real admin console UI always does), not a bulk update().
        flag = FeatureFlag.objects.get(key=key)
        flag.enabled = False
        flag.save(update_fields=["enabled"])

    def test_ai_chat_disabled_blocks_regenerate(self):
        self._disable("ai_chat")
        from chat.models import ChatSession as CS, Message
        session = CS.objects.create(user=self.user, title="t")
        user_msg = Message.objects.create(session=session, role="user", content="hi")
        assistant_msg = Message.objects.create(session=session, role="assistant", content="hello", parent=user_msg)
        response = self.client.post(reverse("regenerate_message", args=[assistant_msg.id]))
        self.assertIn("disabled", response.json()["message"].lower())

    def test_analytics_disabled_redirects_home(self):
        self._disable("analytics")
        response = self.client.get(reverse("analytics_dashboard"))
        self.assertRedirects(response, reverse("home"))

    def test_registration_disabled_shows_closed_page(self):
        self._disable("registration")
        self.client.logout()
        response = self.client.get(reverse("account_signup"))
        self.assertContains(response, "REGISTRATION CLOSED")


class BroadcastStatusTests(TestCase):
    def test_active_with_no_schedule(self):
        b = Broadcast.objects.create(message="hi", active=True)
        self.assertEqual(b.status, "active")
        self.assertTrue(b.is_currently_visible())

    def test_inactive_flag_wins_regardless_of_schedule(self):
        b = Broadcast.objects.create(message="hi", active=False, starts_at=timezone.now() - timedelta(hours=1))
        self.assertEqual(b.status, "inactive")

    def test_scheduled_for_the_future(self):
        b = Broadcast.objects.create(message="hi", active=True, starts_at=timezone.now() + timedelta(hours=1))
        self.assertEqual(b.status, "scheduled")
        self.assertFalse(b.is_currently_visible())

    def test_expired(self):
        b = Broadcast.objects.create(message="hi", active=True, ends_at=timezone.now() - timedelta(hours=1))
        self.assertEqual(b.status, "expired")
        self.assertFalse(b.is_currently_visible())

    def test_currently_within_window(self):
        b = Broadcast.objects.create(
            message="hi", active=True,
            starts_at=timezone.now() - timedelta(hours=1),
            ends_at=timezone.now() + timedelta(hours=1),
        )
        self.assertEqual(b.status, "active")


class UserListFilterTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(username="admin", password="testpass123", email="admin@example.com")
        self.client.force_login(self.superuser)
        self.staff = User.objects.create_user(username="staffer", password="x", is_staff=True, email="staffer@example.com")
        self.regular = User.objects.create_user(username="regular", password="x", email="regular@example.com")

    def test_admin_filter_shows_only_staff_and_superusers(self):
        response = self.client.get(reverse("admin_users_list") + "?admin=yes")
        self.assertContains(response, "staffer@example.com")
        self.assertNotContains(response, "regular@example.com")

    def test_verified_filter(self):
        from allauth.account.models import EmailAddress
        EmailAddress.objects.create(user=self.regular, email="regular@example.com", verified=True, primary=True)
        response = self.client.get(reverse("admin_users_list") + "?verified=yes")
        self.assertContains(response, "regular@example.com")
        self.assertNotContains(response, "staffer@example.com")


class AuditLogCaptureTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(username="admin", password="testpass123", email="admin@example.com")
        self.target = User.objects.create_user(username="target", password="testpass123", email="target@example.com")

    def test_action_captures_ip_and_browser(self):
        client = Client(HTTP_USER_AGENT="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36")
        client.force_login(self.superuser)
        client.post(reverse("admin_user_detail", args=[self.target.id]), {"action": "block"})
        log = AdminAuditLog.objects.filter(action="block", target_user=self.target).first()
        self.assertIsNotNone(log)
        self.assertIn("Chrome", log.browser)
        self.assertTrue(log.success)

    def test_search_by_target_username(self):
        AdminAuditLog.objects.create(actor=self.superuser, action="block", target_user=self.target, detail="x")
        client = Client()
        client.force_login(self.superuser)
        response = client.get(reverse("admin_audit_log") + "?q=target")
        self.assertContains(response, "block")

    def test_feature_flag_create_is_audit_logged(self):
        client = Client()
        client.force_login(self.superuser)
        client.post(reverse("admin_feature_flags"), {"action": "create", "key": "brand_new_flag"})
        self.assertTrue(AdminAuditLog.objects.filter(action="feature_flag_create").exists())
