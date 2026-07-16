"""Tests for the custom Super Admin Console (chat/admin_views.py) and the
security/maintenance infrastructure it depends on (chat/signals.py,
chat/middleware.py). Kept in its own file, mirroring admin_views.py being
separate from views.py."""
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.test import TestCase, Client
from django.urls import reverse

from chat.models import (
    AdminAuditLog, Broadcast, ChatSession, FailedLoginAttempt, FeatureFlag,
    Message, SecurityEvent, UserNote, UserProfile,
)
from chat.services.message_tree import append_turn

User = get_user_model()


class AdminConsoleAccessControlTests(TestCase):
    """Every admin console view must be a 404/redirect for anyone who isn't
    an active superuser - this is the actual security boundary."""

    def setUp(self):
        self.regular_user = User.objects.create_user(username="regular", password="testpass123")
        self.staff_user = User.objects.create_user(username="staffer", password="testpass123", is_staff=True)
        self.superuser = User.objects.create_superuser(username="admin", password="testpass123", email="admin@example.com")
        self.admin_urls = [
            reverse("admin_dashboard"),
            reverse("admin_users_list"),
            reverse("admin_audit_log"),
            reverse("admin_security"),
            reverse("admin_feature_flags"),
            reverse("admin_broadcasts"),
        ]

    def test_anonymous_user_redirected(self):
        for url in self.admin_urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, f"{url} did not redirect an anonymous user")

    def test_regular_user_cannot_access(self):
        self.client.force_login(self.regular_user)
        for url in self.admin_urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, f"{url} let a regular user through")

    def test_staff_but_not_superuser_cannot_access(self):
        self.client.force_login(self.staff_user)
        for url in self.admin_urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, f"{url} let a staff-only user through")

    def test_superuser_can_access(self):
        self.client.force_login(self.superuser)
        for url in self.admin_urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, f"{url} blocked a real superuser")

    def test_blocked_superuser_cannot_access(self):
        self.superuser.is_active = False
        self.superuser.save()
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("admin_dashboard"))
        # An inactive account can't even establish a force_login session
        # that Django's own auth middleware will honor on the next request.
        self.assertNotEqual(response.status_code, 200)


class AdminUserManagementTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(username="admin", password="testpass123", email="admin@example.com")
        self.target = User.objects.create_user(username="target", password="testpass123", email="target@example.com")
        UserProfile.get_or_create_for(self.target)
        self.client.force_login(self.superuser)

    def test_users_list_search_by_username(self):
        User.objects.create_user(username="someone_else", password="testpass123")
        response = self.client.get(reverse("admin_users_list"), {"q": "target"})
        usernames = [u.username for u in response.context["page"].object_list]
        self.assertIn("target", usernames)
        self.assertNotIn("someone_else", usernames)

    def test_users_list_status_filter_banned(self):
        profile = UserProfile.get_or_create_for(self.target)
        profile.is_banned = True
        profile.save()
        response = self.client.get(reverse("admin_users_list"), {"status": "banned"})
        usernames = [u.username for u in response.context["page"].object_list]
        self.assertIn("target", usernames)

    def test_block_user(self):
        self.client.post(reverse("admin_user_detail", args=[self.target.id]), {"action": "block"})
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_active)
        self.assertTrue(AdminAuditLog.objects.filter(action="block", target_user=self.target).exists())

    def test_unblock_user(self):
        self.target.is_active = False
        self.target.save()
        self.client.post(reverse("admin_user_detail", args=[self.target.id]), {"action": "unblock"})
        self.target.refresh_from_db()
        self.assertTrue(self.target.is_active)

    def test_ban_user_also_deactivates_login(self):
        self.client.post(reverse("admin_user_detail", args=[self.target.id]), {"action": "ban", "reason": "spam"})
        self.target.refresh_from_db()
        profile = UserProfile.objects.get(user=self.target)
        self.assertTrue(profile.is_banned)
        self.assertEqual(profile.ban_reason, "spam")
        self.assertFalse(self.target.is_active)

    def test_unban_user_restores_login(self):
        profile = UserProfile.objects.get(user=self.target)
        profile.is_banned = True
        profile.save()
        self.target.is_active = False
        self.target.save()
        self.client.post(reverse("admin_user_detail", args=[self.target.id]), {"action": "unban"})
        self.target.refresh_from_db()
        profile.refresh_from_db()
        self.assertFalse(profile.is_banned)
        self.assertTrue(self.target.is_active)

    def test_suspend_user_sets_expiry(self):
        self.client.post(reverse("admin_user_detail", args=[self.target.id]), {
            "action": "suspend", "suspend_days": "3", "reason": "cooldown",
        })
        profile = UserProfile.objects.get(user=self.target)
        self.assertTrue(profile.is_suspended)
        self.assertEqual(profile.suspend_reason, "cooldown")

    def test_unsuspend_user(self):
        profile = UserProfile.objects.get(user=self.target)
        from django.utils import timezone
        from datetime import timedelta
        profile.suspended_until = timezone.now() + timedelta(days=1)
        profile.save()
        self.client.post(reverse("admin_user_detail", args=[self.target.id]), {"action": "unsuspend"})
        profile.refresh_from_db()
        self.assertFalse(profile.is_suspended)

    def test_force_logout_kills_sessions(self):
        other_client = Client()
        other_client.login(username="target", password="testpass123")
        self.assertIn(
            other_client.session.session_key,
            list(Session.objects.values_list('session_key', flat=True)),
        )

        self.client.post(reverse("admin_user_detail", args=[self.target.id]), {"action": "force_logout"})

        self.assertEqual(Session.objects.filter(session_key=other_client.session.session_key).count(), 0)

    def test_delete_chats(self):
        session = ChatSession.objects.create(user=self.target, title="test")
        append_turn(session, "hi", "hello")
        self.client.post(reverse("admin_user_detail", args=[self.target.id]), {"action": "delete_chats"})
        self.assertEqual(ChatSession.objects.filter(user=self.target).count(), 0)

    def test_verify_email(self):
        self.client.post(reverse("admin_user_detail", args=[self.target.id]), {"action": "verify_email"})
        from allauth.account.models import EmailAddress
        self.assertTrue(EmailAddress.objects.filter(user=self.target, verified=True).exists())

    def test_change_role_to_staff(self):
        self.client.post(reverse("admin_user_detail", args=[self.target.id]), {"action": "change_role", "role": "staff"})
        self.target.refresh_from_db()
        self.assertTrue(self.target.is_staff)
        self.assertFalse(self.target.is_superuser)

    def test_change_role_to_superuser(self):
        self.client.post(reverse("admin_user_detail", args=[self.target.id]), {"action": "change_role", "role": "superuser"})
        self.target.refresh_from_db()
        self.assertTrue(self.target.is_staff)
        self.assertTrue(self.target.is_superuser)

    def test_add_note(self):
        self.client.post(reverse("admin_user_detail", args=[self.target.id]), {"action": "add_note", "note": "Contacted about billing"})
        self.assertTrue(UserNote.objects.filter(user=self.target, note="Contacted about billing").exists())

    def test_reset_password_sends_otp(self):
        from django.core import mail
        from chat.models import PasswordResetOTP
        self.client.post(reverse("admin_user_detail", args=[self.target.id]), {"action": "reset_password"})
        self.assertTrue(PasswordResetOTP.objects.filter(user=self.target).exists())
        self.assertEqual(len(mail.outbox), 1)

    def test_every_action_is_audited(self):
        self.client.post(reverse("admin_user_detail", args=[self.target.id]), {"action": "block"})
        log = AdminAuditLog.objects.filter(target_user=self.target).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.actor, self.superuser)
        self.assertEqual(log.action, "block")


class FeatureFlagTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(username="admin", password="testpass123", email="admin@example.com")
        self.client.force_login(self.superuser)

    def test_is_enabled_default_when_flag_absent(self):
        self.assertTrue(FeatureFlag.is_enabled("nonexistent_flag", default=True))
        self.assertFalse(FeatureFlag.is_enabled("nonexistent_flag", default=False))

    def test_create_flag_via_console(self):
        self.client.post(reverse("admin_feature_flags"), {"action": "create", "key": "beta_feature", "description": "test"})
        self.assertTrue(FeatureFlag.objects.filter(key="beta_feature").exists())

    def test_toggle_flag(self):
        FeatureFlag.objects.create(key="test_flag", enabled=False)
        self.client.post(reverse("admin_feature_flags"), {"action": "toggle", "key": "test_flag"})
        self.assertTrue(FeatureFlag.objects.get(key="test_flag").enabled)


class MaintenanceModeMiddlewareTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="dhruv", password="testpass123")
        self.superuser = User.objects.create_superuser(username="admin", password="testpass123", email="a@example.com")

    def test_normal_users_blocked_during_maintenance(self):
        # update_or_create, not create: a data migration now seeds this flag
        # (disabled) for every environment, so it already exists here.
        FeatureFlag.objects.update_or_create(key="maintenance_mode", defaults={"enabled": True})
        self.client.force_login(self.user)
        response = self.client.get("/")
        self.assertEqual(response.status_code, 503)

    def test_superuser_bypasses_maintenance(self):
        FeatureFlag.objects.update_or_create(key="maintenance_mode", defaults={"enabled": True})
        self.client.force_login(self.superuser)
        response = self.client.get("/")
        self.assertNotEqual(response.status_code, 503)

    def test_no_maintenance_flag_means_normal_operation(self):
        # The seeded row exists but defaults to disabled - same observable
        # behavior as "no flag at all" from is_enabled()'s point of view.
        self.client.force_login(self.user)
        response = self.client.get("/")
        self.assertNotEqual(response.status_code, 503)

    def test_health_check_exempt_during_maintenance(self):
        FeatureFlag.objects.update_or_create(key="maintenance_mode", defaults={"enabled": True})
        response = self.client.get(reverse("health_check"))
        self.assertEqual(response.status_code, 200)


class SecuritySignalTests(TestCase):
    def test_failed_login_is_recorded(self):
        User.objects.create_user(username="dhruv", password="realpassword", email="dhruv@example.com")
        self.client.post(reverse("account_login"), {"login": "dhruv@example.com", "password": "wrongpassword"})
        self.assertTrue(FailedLoginAttempt.objects.filter(email_attempted="dhruv@example.com").exists())

    def test_successful_login_creates_security_event(self):
        user = User.objects.create_user(username="dhruv", password="realpassword", email="dhruv@example.com")
        self.client.post(reverse("account_login"), {"login": "dhruv@example.com", "password": "realpassword"})
        self.assertTrue(SecurityEvent.objects.filter(user=user, event_type="login").exists())


class ImageFavoriteTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="dhruv", password="testpass123")
        self.other_user = User.objects.create_user(username="mallory", password="testpass123")
        self.client.force_login(self.user)
        self.session = ChatSession.objects.create(user=self.user, title="T")
        _user_msg, self.image_msg = append_turn(
            self.session, "draw a cat", "", assistant_extra_data={
                "type": "image", "image_url": "https://example.com/cat.png",
                "model_used": "Pollinations AI", "prompt": "a cat", "width": 1024, "height": 1024,
            },
        )

    def test_toggle_favorite_sets_flag(self):
        response = self.client.post(reverse("toggle_favorite_image", args=[self.image_msg.id]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["favorited"])
        self.image_msg.refresh_from_db()
        self.assertTrue(self.image_msg.extra_data["favorited"])

    def test_toggle_favorite_twice_unfavorites(self):
        self.client.post(reverse("toggle_favorite_image", args=[self.image_msg.id]))
        response = self.client.post(reverse("toggle_favorite_image", args=[self.image_msg.id]))
        self.assertFalse(response.json()["favorited"])

    def test_cannot_favorite_non_image_message(self):
        _u, text_msg = append_turn(self.session, "hello", "hi there")
        response = self.client.post(reverse("toggle_favorite_image", args=[text_msg.id]))
        self.assertEqual(response.status_code, 400)

    def test_cannot_favorite_another_users_image(self):
        other_session = ChatSession.objects.create(user=self.other_user, title="private")
        _u, other_image_msg = append_turn(
            other_session, "draw a dog", "", assistant_extra_data={"type": "image", "image_url": "x"},
        )
        response = self.client.post(reverse("toggle_favorite_image", args=[other_image_msg.id]))
        self.assertEqual(response.status_code, 404)


class BroadcastTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(username="admin", password="testpass123", email="a@example.com")
        self.user = User.objects.create_user(username="dhruv", password="testpass123")

    def test_create_broadcast_deactivates_previous(self):
        self.client.force_login(self.superuser)
        Broadcast.objects.create(message="old", active=True)
        self.client.post(reverse("admin_broadcasts"), {"action": "create", "message": "new broadcast", "level": "warning"})
        self.assertEqual(Broadcast.objects.filter(active=True).count(), 1)
        self.assertEqual(Broadcast.objects.filter(active=True).first().message, "new broadcast")

    def test_active_broadcast_shown_on_chat_home(self):
        Broadcast.objects.create(message="Scheduled maintenance tonight", active=True, level="warning")
        self.client.force_login(self.user)
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Scheduled maintenance tonight")

    def test_deactivate_broadcast(self):
        self.client.force_login(self.superuser)
        b = Broadcast.objects.create(message="test", active=True)
        self.client.post(reverse("admin_broadcasts"), {"action": "deactivate", "broadcast_id": b.id})
        b.refresh_from_db()
        self.assertFalse(b.active)
