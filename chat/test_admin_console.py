"""Tests for the custom Super Admin Console (chat/admin_views.py) and the
security/maintenance infrastructure it depends on (chat/signals.py,
chat/middleware.py). Kept in its own file, mirroring admin_views.py being
separate from views.py."""
import csv
import io
import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from chat.models import (
    AdminAuditLog, Broadcast, ChatSession, ErrorLog, FailedLoginAttempt, FeatureFlag,
    Message, RecoveryCode, Role, SecurityEvent, UsageEvent, UserNote, UserProfile,
)
from chat.services.message_tree import append_turn

User = get_user_model()


class AdminConsoleAccessControlTests(TestCase):
    """Every admin console view must reject anyone below Role.ADMIN - see
    chat/test_rbac.py for the full RBAC decorator/hierarchy test coverage;
    this class just confirms the URL-level gating is still wired up on
    every one of these routes specifically.

    Since the RBAC upgrade: an authenticated-but-under-privileged user gets
    a real 403 (require_role raises PermissionDenied), not the old
    redirect-to-home - only a genuinely anonymous request still redirects
    (to the login page, via @login_required running first). is_staff=True
    alone now resolves to Role.ADMIN (see UserProfile.get_or_create_for's
    and chat/permissions.py's user_role() docstrings) and DOES grant
    console access - that's intentional, not a gap: is_staff/is_superuser
    are kept meaningful in both directions for Django-admin compatibility."""

    def setUp(self):
        self.regular_user = User.objects.create_user(username="regular", password="testpass123")
        self.staff_user = User.objects.create_user(username="staffer", password="testpass123", is_staff=True)
        self.superuser = User.objects.create_superuser(username="admin", password="testpass123", email="admin@example.com")
        self.admin_urls = [
            reverse("admin_dashboard"),
            reverse("admin_live_platform"),
            reverse("admin_live_platform_data"),
            reverse("admin_live_log_stream"),
            reverse("admin_quick_search"),
            reverse("admin_users_list"),
            reverse("admin_users_export_csv"),
            reverse("admin_audit_log"),
            reverse("admin_audit_log_export_csv"),
            reverse("admin_security"),
            reverse("admin_feature_flags"),
            reverse("admin_broadcasts"),
            reverse("admin_errors"),
            reverse("admin_system_health"),
            reverse("admin_system_health_data"),
            reverse("admin_roles"),
            reverse("admin_reports"),
            reverse("admin_ai_control"),
            reverse("admin_settings"),
        ]

    def test_anonymous_user_redirected(self):
        for url in self.admin_urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, f"{url} did not redirect an anonymous user")

    def test_regular_user_cannot_access(self):
        self.client.force_login(self.regular_user)
        for url in self.admin_urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 403, f"{url} let a regular user through")

    def test_staff_flag_alone_grants_admin_tier_access(self):
        # is_staff=True with no profile row resolves to Role.ADMIN (the
        # same is_staff/is_superuser -> role bootstrap the RBAC migration
        # itself uses for pre-existing accounts) - Role.ADMIN has console
        # access by spec, so this is correct, not a security hole.
        self.client.force_login(self.staff_user)
        for url in self.admin_urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, f"{url} blocked an Admin-tier (is_staff) user")

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

    def test_change_role_to_admin(self):
        # RBAC upgrade: role is now a 6-tier UserProfile.role field, not a
        # 3-way is_staff/is_superuser combination - is_staff/is_superuser
        # are still checked below, but only as a side effect kept in sync
        # by chat/permissions.py's sync_django_flags, not the source of truth.
        self.client.post(reverse("admin_user_detail", args=[self.target.id]), {"action": "change_role", "role": "admin"})
        self.target.refresh_from_db()
        profile = UserProfile.objects.get(user=self.target)
        self.assertEqual(profile.role, "admin")
        self.assertTrue(self.target.is_staff)
        self.assertFalse(self.target.is_superuser)

    def test_change_role_to_super_admin(self):
        self.client.post(reverse("admin_user_detail", args=[self.target.id]), {"action": "change_role", "role": "super_admin"})
        self.target.refresh_from_db()
        profile = UserProfile.objects.get(user=self.target)
        self.assertEqual(profile.role, "super_admin")
        self.assertTrue(self.target.is_staff)
        self.assertTrue(self.target.is_superuser)

    def test_add_note(self):
        self.client.post(reverse("admin_user_detail", args=[self.target.id]), {"action": "add_note", "note": "Contacted about billing"})
        self.assertTrue(UserNote.objects.filter(user=self.target, note="Contacted about billing").exists())

    def test_reset_password_generates_a_recovery_code(self):
        from chat.models import RecoveryCode
        self.client.post(reverse("admin_user_detail", args=[self.target.id]), {"action": "reset_password"})
        self.assertTrue(RecoveryCode.objects.filter(user=self.target).exists())

    def test_reset_password_on_google_only_account_does_not_generate_a_code(self):
        from chat.models import RecoveryCode
        self.target.set_unusable_password()
        self.target.save()
        self.client.post(reverse("admin_user_detail", args=[self.target.id]), {"action": "reset_password"})
        self.assertFalse(RecoveryCode.objects.filter(user=self.target).exists())

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


class LivePlatformTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(username="admin", password="testpass123", email="a@example.com")
        self.client.force_login(self.superuser)

    def test_page_renders(self):
        response = self.client.get(reverse("admin_live_platform"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "LIVE PLATFORM MONITOR")

    def test_data_endpoint_shape(self):
        response = self.client.get(reverse("admin_live_platform_data"))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        for key in (
            "online_users", "requests_last_minute", "avg_latency_ms", "db_latency_ms",
            "active_chat_60s", "active_image_60s", "active_vision_60s",
            "recent_errors_5m", "feed", "server_time",
        ):
            self.assertIn(key, data)

    def test_recent_usage_event_counted_as_active(self):
        UsageEvent.objects.create(
            user=self.superuser, provider="groq", model_id="cyber-max",
            event_type="chat", prompt_tokens=5, completion_tokens=5,
        )
        data = self.client.get(reverse("admin_live_platform_data")).json()
        self.assertEqual(data["active_chat_60s"], 1)
        self.assertEqual(data["requests_last_minute"], 1)

    def test_feed_includes_recent_security_events_and_audit_actions(self):
        SecurityEvent.objects.create(user=self.superuser, event_type="login", severity="info")
        AdminAuditLog.objects.create(actor=self.superuser, action="block", target_user=self.superuser)
        data = self.client.get(reverse("admin_live_platform_data")).json()
        self.assertGreaterEqual(len(data["feed"]), 2)


class AdminQuickSearchTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(username="admin", password="testpass123", email="a@example.com")
        self.client.force_login(self.superuser)
        User.objects.create_user(username="findme", email="findme@example.com", password="x")
        User.objects.create_user(username="other", email="other@example.com", password="x")

    def test_empty_query_returns_empty_groups(self):
        data = self.client.get(reverse("admin_quick_search")).json()
        self.assertEqual(data["users"], [])
        self.assertEqual(data["chats"], [])

    def test_matches_by_username(self):
        data = self.client.get(reverse("admin_quick_search"), {"q": "findme"}).json()
        usernames = [r["username"] for r in data["users"]]
        self.assertIn("findme", usernames)
        self.assertNotIn("other", usernames)

    def test_matches_by_email(self):
        data = self.client.get(reverse("admin_quick_search"), {"q": "findme@example.com"}).json()
        self.assertEqual(len(data["users"]), 1)
        self.assertEqual(data["users"][0]["username"], "findme")

    def test_matches_chat_session_by_title(self):
        user = User.objects.filter(username="findme").first()
        ChatSession.objects.create(user=user, title="Unique Chat Title About Rockets")
        data = self.client.get(reverse("admin_quick_search"), {"q": "Rockets"}).json()
        titles = [c["title"] for c in data["chats"]]
        self.assertIn("Unique Chat Title About Rockets", titles)

    def test_matches_feature_flag_by_key(self):
        FeatureFlag.objects.create(key="unique_search_flag", description="test")
        data = self.client.get(reverse("admin_quick_search"), {"q": "unique_search_flag"}).json()
        keys = [f["key"] for f in data["feature_flags"]]
        self.assertIn("unique_search_flag", keys)


class UsersListFilterSortExportTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(username="admin", password="testpass123", email="a@example.com")
        self.client.force_login(self.superuser)
        self.alice = User.objects.create_user(username="alice", email="alice@example.com", password="x")
        self.bob = User.objects.create_user(username="bob", email="bob@example.com", password="x")
        UserProfile.objects.filter(user=self.bob).update(role=Role.MODERATOR) if UserProfile.objects.filter(user=self.bob).exists() else UserProfile.objects.create(user=self.bob, role=Role.MODERATOR)

    def test_role_filter(self):
        response = self.client.get(reverse("admin_users_list"), {"role": "moderator"})
        usernames = [u.username for u in response.context["page"]]
        self.assertIn("bob", usernames)
        self.assertNotIn("alice", usernames)

    def test_sort_by_username_ascending(self):
        response = self.client.get(reverse("admin_users_list"), {"sort": "username"})
        usernames = [u.username for u in response.context["page"]]
        self.assertEqual(usernames, sorted(usernames))

    def test_sort_toggle_reverses_direction(self):
        response = self.client.get(reverse("admin_users_list"), {"sort": "-username"})
        usernames = [u.username for u in response.context["page"]]
        self.assertEqual(usernames, sorted(usernames, reverse=True))

    def test_invalid_sort_falls_back_to_default(self):
        response = self.client.get(reverse("admin_users_list"), {"sort": "not_a_real_field; DROP TABLE"})
        self.assertEqual(response.status_code, 200)

    def test_csv_export_contains_filtered_rows(self):
        response = self.client.get(reverse("admin_users_export_csv"), {"role": "moderator"})
        self.assertEqual(response["Content-Type"], "text/csv")
        rows = list(csv.reader(io.StringIO(response.content.decode())))
        usernames = [r[1] for r in rows[1:]]
        self.assertIn("bob", usernames)
        self.assertNotIn("alice", usernames)

    def test_csv_export_is_logged(self):
        self.client.get(reverse("admin_users_export_csv"))
        self.assertTrue(AdminAuditLog.objects.filter(action="export_users_csv", actor=self.superuser).exists())


class AuditLogExportTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(username="admin", password="testpass123", email="a@example.com")
        self.client.force_login(self.superuser)
        self.target = User.objects.create_user(username="target", password="x")
        AdminAuditLog.objects.create(actor=self.superuser, action="block", target_user=self.target, detail="test")

    def test_csv_export_contains_expected_columns_and_row(self):
        response = self.client.get(reverse("admin_audit_log_export_csv"))
        self.assertEqual(response["Content-Type"], "text/csv")
        rows = list(csv.reader(io.StringIO(response.content.decode())))
        self.assertEqual(rows[0], ["when", "actor", "action", "target", "detail", "ip_address", "browser", "success"])
        actions = [r[2] for r in rows[1:]]
        self.assertIn("block", actions)

    def test_csv_export_respects_action_filter(self):
        AdminAuditLog.objects.create(actor=self.superuser, action="unban", target_user=self.target)
        response = self.client.get(reverse("admin_audit_log_export_csv"), {"action": "unban"})
        rows = list(csv.reader(io.StringIO(response.content.decode())))
        actions = [r[2] for r in rows[1:]]
        self.assertEqual(set(actions), {"unban"})


class DashboardExpansionTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(username="admin", password="testpass123", email="a@example.com")
        self.client.force_login(self.superuser)

    def test_daily_active_users_counts_usage_only_activity(self):
        # A user with AI usage today but no login event today must still
        # count toward DAU - this is exactly the bug being fixed (DAU used
        # to just redisplay the ~5min "Online Now" figure, which only ever
        # reflects logins). force_login() in setUp already fires a real
        # login signal for the superuser, so online_users is correctly 1 -
        # the bug-fix assertion is that DAU also counts quiet_user's
        # usage-only activity, growing DAU past that login-only figure.
        quiet_user = User.objects.create_user(username="quiet", password="x")
        UsageEvent.objects.create(
            user=quiet_user, provider="groq", model_id="cyber-max",
            event_type="chat", prompt_tokens=1, completion_tokens=1,
        )
        response = self.client.get(reverse("admin_dashboard"))
        self.assertEqual(response.context["online_users"], 1)
        self.assertEqual(response.context["daily_active_users"], 2)

    def test_peak_hours_json_has_24_buckets(self):
        response = self.client.get(reverse("admin_dashboard"))
        peak_hours = json.loads(response.context["peak_hours_json"])
        self.assertEqual(len(peak_hours), 24)
        self.assertEqual([p["hour"] for p in peak_hours], list(range(24)))

    def test_most_active_users_reflects_usage(self):
        heavy_user = User.objects.create_user(username="heavy", password="x")
        for _ in range(3):
            UsageEvent.objects.create(
                user=heavy_user, provider="groq", model_id="cyber-max",
                event_type="chat", prompt_tokens=1, completion_tokens=1,
            )
        response = self.client.get(reverse("admin_dashboard"))
        top = response.context["most_active_users"]
        self.assertTrue(any(row["user__username"] == "heavy" and row["requests"] == 3 for row in top))

    def test_db_stats_present(self):
        response = self.client.get(reverse("admin_dashboard"))
        db_stats = response.context["db_stats"]
        for key in ("users", "chat_sessions", "messages", "usage_events", "security_events", "audit_log_entries"):
            self.assertIn(key, db_stats)

    def test_feature_flags_glance_present(self):
        FeatureFlag.objects.create(key="a_test_flag", enabled=True)
        response = self.client.get(reverse("admin_dashboard"))
        keys = [f.key for f in response.context["feature_flags_glance"]]
        self.assertIn("a_test_flag", keys)


class SecurityBreakdownTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(username="admin", password="testpass123", email="a@example.com")
        self.client.force_login(self.superuser)

    def test_top_ips_browsers_devices_populated(self):
        for _ in range(3):
            SecurityEvent.objects.create(
                user=self.superuser, event_type="login", severity="info",
                ip_address="10.0.0.1", browser="Chrome", device="Desktop",
            )
        response = self.client.get(reverse("admin_security"))
        top_ips = response.context["top_ips"]
        top_browsers = response.context["top_browsers"]
        top_devices = response.context["top_devices"]
        self.assertTrue(any(row["ip_address"] == "10.0.0.1" and row["count"] == 3 for row in top_ips))
        self.assertTrue(any(row["browser"] == "Chrome" and row["count"] == 3 for row in top_browsers))
        self.assertTrue(any(row["device"] == "Desktop" and row["count"] == 3 for row in top_devices))


class ExportUserDataQueryEfficiencyTests(TestCase):
    """Locks in the fix for the N+1 found in admin_export_user_data: query
    count for exporting a user's data must not grow linearly with how many
    chat sessions they have (a Prefetch with an explicit queryset, not a
    bare prefetch_related('thread') followed by .order_by() on it)."""

    def setUp(self):
        self.superuser = User.objects.create_superuser(username="admin", password="testpass123", email="a@example.com")
        self.client.force_login(self.superuser)
        self.target = User.objects.create_user(username="target", password="x")

    def _query_count_for_n_sessions(self, n):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        ChatSession.objects.filter(user=self.target).delete()
        for i in range(n):
            session = ChatSession.objects.create(user=self.target, title=f"session {i}")
            append_turn(session, f"hello {i}", f"hi {i}")
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(reverse("admin_export_user_data", args=[self.target.id]))
        return len(ctx.captured_queries)

    def test_query_count_does_not_scale_with_session_count(self):
        few = self._query_count_for_n_sessions(2)
        many = self._query_count_for_n_sessions(10)
        # A handful of extra queries (pagination/aggregates) is fine; a real
        # N+1 would add roughly one query per extra session (8 more here).
        self.assertLess(many - few, 5, f"query count grew from {few} to {many} - looks like an N+1")


class UserDetailRecoveryCodeStatusTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(username="admin", password="testpass123", email="a@example.com")
        self.client.force_login(self.superuser)
        self.target = User.objects.create_user(username="target", password="testpass123", email="target@example.com")

    def test_shows_not_set_when_no_recovery_code(self):
        response = self.client.get(reverse("admin_user_detail", args=[self.target.id]))
        self.assertContains(response, "NOT SET")

    def test_shows_set_with_timestamp_when_present(self):
        RecoveryCode.generate_for(self.target)
        response = self.client.get(reverse("admin_user_detail", args=[self.target.id]))
        self.assertContains(response, "SET")

    def test_shows_na_for_google_only_account(self):
        self.target.set_unusable_password()
        self.target.save()
        response = self.client.get(reverse("admin_user_detail", args=[self.target.id]))
        self.assertContains(response, "N/A - signs in with Google")

    def test_reset_password_action_still_generates_a_new_code(self):
        self.client.post(reverse("admin_user_detail", args=[self.target.id]), {"action": "reset_password"})
        self.assertTrue(RecoveryCode.objects.filter(user=self.target).exists())


class ErrorLogModelTests(TestCase):
    def test_first_occurrence_creates_a_row_with_count_one(self):
        err = ErrorLog.record("chat_provider", "Something broke")
        self.assertEqual(err.count, 1)
        self.assertFalse(err.resolved)

    def test_duplicate_error_increments_count_instead_of_creating_a_row(self):
        ErrorLog.record("chat_provider", "Something broke")
        ErrorLog.record("chat_provider", "Something broke")
        ErrorLog.record("chat_provider", "Something broke")
        self.assertEqual(ErrorLog.objects.count(), 1)
        self.assertEqual(ErrorLog.objects.first().count, 3)

    def test_different_category_is_a_separate_group(self):
        ErrorLog.record("chat_provider", "Same message")
        ErrorLog.record("vision_provider", "Same message")
        self.assertEqual(ErrorLog.objects.count(), 2)

    def test_resolved_error_recurring_starts_a_fresh_row(self):
        first = ErrorLog.record("chat_provider", "Something broke")
        first.resolved = True
        first.save(update_fields=['resolved'])
        second = ErrorLog.record("chat_provider", "Something broke")
        self.assertNotEqual(first.id, second.id)
        self.assertFalse(second.resolved)
        self.assertEqual(second.count, 1)


class ErrorCenterViewTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(username="admin", password="testpass123", email="a@example.com")
        self.client.force_login(self.superuser)

    def test_unresolved_filter_is_default(self):
        ErrorLog.record("chat_provider", "open error")
        resolved = ErrorLog.record("chat_provider", "resolved error")
        resolved.resolved = True
        resolved.save(update_fields=['resolved'])
        response = self.client.get(reverse("admin_errors"))
        messages_shown = [e.message for e in response.context["page"]]
        self.assertIn("open error", messages_shown)
        self.assertNotIn("resolved error", messages_shown)

    def test_category_filter(self):
        ErrorLog.record("chat_provider", "chat error")
        ErrorLog.record("vision_provider", "vision error")
        response = self.client.get(reverse("admin_errors"), {"category": "vision_provider", "status": ""})
        messages_shown = [e.message for e in response.context["page"]]
        self.assertIn("vision error", messages_shown)
        self.assertNotIn("chat error", messages_shown)

    def test_resolve_action_marks_resolved_and_logs(self):
        err = ErrorLog.record("chat_provider", "needs fixing")
        self.client.post(reverse("admin_error_resolve", args=[err.id]))
        err.refresh_from_db()
        self.assertTrue(err.resolved)
        self.assertEqual(err.resolved_by, self.superuser)
        self.assertTrue(AdminAuditLog.objects.filter(action="error_resolved").exists())

    def test_provider_error_capture_via_simba_logger(self):
        from chat.utils.logger import SimbaLogger
        SimbaLogger().log_request(
            provider="groq", latency=0.1, prompt_length=5, response_length=0,
            error="Provider timed out", category="chat_provider",
        )
        self.assertTrue(ErrorLog.objects.filter(category="chat_provider", message="Provider timed out").exists())

    def test_unhandled_exception_signal_creates_error_log(self):
        from django.core.signals import got_request_exception
        try:
            raise ValueError("boom")
        except ValueError:
            got_request_exception.send(sender=None, request=None)
        self.assertTrue(ErrorLog.objects.filter(category="unhandled_exception", message__icontains="boom").exists())


class SystemHealthViewTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(username="admin", password="testpass123", email="a@example.com")
        self.client.force_login(self.superuser)

    def test_page_renders(self):
        response = self.client.get(reverse("admin_system_health"))
        self.assertEqual(response.status_code, 200)

    def test_data_endpoint_shape(self):
        data = self.client.get(reverse("admin_system_health_data")).json()
        for key in ("db_ok", "db_latency_ms", "disk", "ram", "cpu", "requests_last_hour",
                    "error_rate_percent", "providers", "queue_status"):
            self.assertIn(key, data)

    def test_pollinations_never_shows_not_configured(self):
        # pollinations.ai is used keyless - there's no POLLINATIONS_API_KEY
        # env var, so it must never be reported as "not configured" the way
        # a genuinely missing key for another provider would be.
        data = self.client.get(reverse("admin_system_health_data")).json()
        self.assertTrue(data["providers"]["pollinations"]["configured"])


class RoleManagementViewTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(username="admin", password="testpass123", email="a@example.com")
        self.client.force_login(self.superuser)

    def test_page_renders_all_roles(self):
        response = self.client.get(reverse("admin_roles"))
        self.assertEqual(response.status_code, 200)
        role_values = [r['value'] for r in response.context["roles"]]
        self.assertEqual(set(role_values), {r for r, _ in Role.choices})

    def test_permission_matrix_reflects_actual_permissions_module(self):
        from chat.permissions import PERMISSIONS
        response = self.client.get(reverse("admin_roles"))
        actions_shown = {row['action'] for row in response.context["permission_matrix"]}
        self.assertEqual(actions_shown, set(PERMISSIONS.keys()))

    def test_role_counts_reflect_real_users(self):
        UserProfile.objects.create(user=User.objects.create_user(username="mod1", password="x"), role=Role.MODERATOR)
        response = self.client.get(reverse("admin_roles"))
        moderator_row = next(r for r in response.context["roles"] if r['value'] == Role.MODERATOR)
        self.assertEqual(moderator_row['count'], 1)


class ReportGeneratorTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(username="admin", password="testpass123", email="a@example.com")
        self.client.force_login(self.superuser)
        self.target = User.objects.create_user(username="target", password="x")

    def test_reports_hub_renders(self):
        response = self.client.get(reverse("admin_reports"))
        self.assertEqual(response.status_code, 200)

    def test_usage_report_contains_real_data(self):
        UsageEvent.objects.create(user=self.target, provider="groq", model_id="cyber-max", event_type="chat", prompt_tokens=10, completion_tokens=5)
        response = self.client.get(reverse("admin_report_download", args=["usage"]))
        self.assertEqual(response["Content-Type"], "text/csv")
        rows = list(csv.reader(io.StringIO(response.content.decode())))
        self.assertEqual(rows[0], ["date", "provider", "model_id", "event_type", "requests", "total_tokens", "total_cost_usd"])
        self.assertTrue(any(r[1] == "groq" for r in rows[1:]))

    def test_images_report_only_includes_image_events(self):
        UsageEvent.objects.create(user=self.target, provider="pollinations", model_id="image-studio", event_type="image")
        UsageEvent.objects.create(user=self.target, provider="groq", model_id="cyber-max", event_type="chat")
        response = self.client.get(reverse("admin_report_download", args=["images"]))
        rows = list(csv.reader(io.StringIO(response.content.decode())))
        self.assertEqual(len(rows) - 1, 1)  # header + exactly one image row

    def test_security_report_respects_period(self):
        # force_login(self.superuser) in setUp already fires a real login
        # SecurityEvent for the admin, so "header only" isn't the right
        # expectation here - what matters is that the 60-day-old event is
        # excluded from a 1-day window while a fresh one is included.
        old_event = SecurityEvent.objects.create(user=self.target, event_type="login", severity="info")
        SecurityEvent.objects.filter(id=old_event.id).update(created_at=timezone.now() - timedelta(days=60))
        response = self.client.get(reverse("admin_report_download", args=["security"]), {"period": "daily"})
        rows = list(csv.reader(io.StringIO(response.content.decode())))
        data_rows = rows[1:]
        self.assertFalse(any(r[1] == "target" for r in data_rows), "the 60-day-old event should be outside a 1-day window")

    def test_errors_report_contains_grouped_errors(self):
        ErrorLog.record("chat_provider", "a recurring problem")
        response = self.client.get(reverse("admin_report_download", args=["errors"]))
        rows = list(csv.reader(io.StringIO(response.content.decode())))
        self.assertTrue(any("a recurring problem" in r[1] for r in rows[1:]))

    def test_unknown_report_type_rejected(self):
        response = self.client.get(reverse("admin_report_download", args=["not-a-report"]))
        self.assertEqual(response.status_code, 403)

    def test_report_download_is_logged(self):
        self.client.get(reverse("admin_report_download", args=["usage"]))
        self.assertTrue(AdminAuditLog.objects.filter(action="report_generated").exists())


class AiControlCenterTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(username="admin", password="testpass123", email="a@example.com")
        self.client.force_login(self.superuser)

    def test_page_renders_with_curated_flags(self):
        response = self.client.get(reverse("admin_ai_control"))
        self.assertEqual(response.status_code, 200)
        keys_shown = [f['key'] for f in response.context["flags"]]
        self.assertEqual(set(keys_shown), {"ai_chat", "image_generation", "vision", "file_upload", "web_search"})

    def test_toggle_creates_flag_if_missing_then_flips_it(self):
        self.assertFalse(FeatureFlag.objects.filter(key="web_search").exists())
        self.client.post(reverse("admin_ai_control"), {"key": "web_search"})
        flag = FeatureFlag.objects.get(key="web_search")
        self.assertFalse(flag.enabled)  # created enabled=True, then immediately flipped off by this same POST

    def test_toggle_rejects_unknown_key(self):
        self.client.post(reverse("admin_ai_control"), {"key": "not_a_real_flag"})
        self.assertFalse(FeatureFlag.objects.filter(key="not_a_real_flag").exists())

    def test_model_registry_shown_with_min_role(self):
        response = self.client.get(reverse("admin_ai_control"))
        model_ids = [m['id'] for m in response.context["models"]]
        self.assertIn("cyber-max", model_ids)
        cyber_max = next(m for m in response.context["models"] if m['id'] == 'cyber-max')
        self.assertEqual(cyber_max['min_role'], 'user')


class SettingsHubViewTests(TestCase):
    def test_page_renders_with_categories_and_system_info(self):
        superuser = User.objects.create_superuser(username="admin", password="testpass123", email="a@example.com")
        self.client.force_login(superuser)
        response = self.client.get(reverse("admin_settings"))
        self.assertEqual(response.status_code, 200)
        category_names = [c['name'] for c in response.context["categories"]]
        for expected in ("Authentication", "Security", "AI", "Models", "Analytics", "Platform", "System"):
            self.assertIn(expected, category_names)
        self.assertIn("database_engine", response.context["system_info"])


class LogRingBufferTests(TestCase):
    def test_ring_buffer_captures_and_returns_records(self):
        import logging
        from chat.log_buffer import RingBufferHandler, get_recent_logs
        logger = logging.getLogger("simba_intel_test_ring_buffer")
        logger.addHandler(RingBufferHandler())
        logger.setLevel(logging.INFO)
        logger.info("a distinctive test log line")
        recent = get_recent_logs(limit=50)
        self.assertTrue(any("a distinctive test log line" in e['message'] for e in recent))

    def test_live_log_stream_endpoint_returns_captured_logs(self):
        import logging
        superuser = User.objects.create_superuser(username="admin", password="testpass123", email="a@example.com")
        self.client.force_login(superuser)
        logging.getLogger("django").warning("another distinctive marker line")
        data = self.client.get(reverse("admin_live_log_stream")).json()
        self.assertTrue(any("another distinctive marker line" in e['message'] for e in data['logs']))


class BroadcastPopupDismissibleTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(username="admin", password="testpass123", email="a@example.com")
        self.user = User.objects.create_user(username="dhruv", password="testpass123")

    def test_create_popup_broadcast(self):
        self.client.force_login(self.superuser)
        self.client.post(reverse("admin_broadcasts"), {
            # dismissible=on: the template's checkbox defaults to checked in
            # a real browser, so a real submission includes it unless an
            # admin explicitly unchecks it - included here to match that.
            "action": "create", "message": "popup test", "level": "warning", "is_popup": "on", "dismissible": "on",
        })
        broadcast = Broadcast.objects.get(message="popup test")
        self.assertTrue(broadcast.is_popup)
        self.assertTrue(broadcast.dismissible)

    def test_non_popup_broadcast_defaults_to_banner(self):
        self.client.force_login(self.superuser)
        self.client.post(reverse("admin_broadcasts"), {"action": "create", "message": "banner test", "level": "info"})
        broadcast = Broadcast.objects.get(message="banner test")
        self.assertFalse(broadcast.is_popup)

    def test_popup_broadcast_renders_as_overlay_on_chat_home(self):
        Broadcast.objects.create(message="Popup announcement", active=True, is_popup=True, dismissible=True)
        self.client.force_login(self.user)
        response = self.client.get(reverse("home"))
        self.assertContains(response, "broadcastPopupOverlay")
        self.assertContains(response, "Popup announcement")

    def test_banner_broadcast_does_not_render_popup_overlay(self):
        # The shared cleanup script always *references*
        # getElementById('broadcastPopupOverlay') defensively (in case a
        # stale localStorage entry exists from a previously-shown popup) -
        # so the bare string legitimately appears in the JS either way.
        # What must actually be absent is the DOM element itself.
        Broadcast.objects.create(message="Banner announcement", active=True, is_popup=False, dismissible=True)
        self.client.force_login(self.user)
        response = self.client.get(reverse("home"))
        self.assertNotContains(response, 'id="broadcastPopupOverlay"')
        self.assertContains(response, 'id="broadcastBanner"')

    def test_non_dismissible_broadcast_has_no_dismiss_button(self):
        # dismissBroadcast() the function is always defined (shared JS) -
        # what must be absent is a call site (an onclick invoking it).
        Broadcast.objects.create(message="Pinned notice", active=True, is_popup=False, dismissible=False)
        self.client.force_login(self.user)
        response = self.client.get(reverse("home"))
        self.assertNotContains(response, 'onclick="dismissBroadcast(')


class PasswordChangedTimelineTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="dhruv", password="OldPass123!", email="dhruv@example.com")

    def test_allauth_password_change_signal_creates_security_event(self):
        from allauth.account.signals import password_changed
        password_changed.send(sender=None, request=None, user=self.user)
        self.assertTrue(SecurityEvent.objects.filter(user=self.user, event_type="password_changed").exists())

    def test_recovery_code_reset_flow_logs_password_changed_explicitly(self):
        recovery_code, raw_code = RecoveryCode.generate_for(self.user)
        self.client.post(reverse("forgot_password"), {"identifier": "dhruv"})
        self.client.post(reverse("verify_recovery_code"), {"code": raw_code})
        self.client.post(reverse("reset_password_recovery"), {
            "password1": "BrandNewPass456!", "password2": "BrandNewPass456!",
        })
        self.assertTrue(SecurityEvent.objects.filter(user=self.user, event_type="password_changed").exists())


class UserTimelineTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(username="admin", password="testpass123", email="a@example.com")
        self.client.force_login(self.superuser)
        self.target = User.objects.create_user(username="target", password="x", email="target@example.com")

    def test_timeline_includes_account_created(self):
        response = self.client.get(reverse("admin_user_detail", args=[self.target.id]))
        texts = [e['text'] for e in response.context["timeline"]]
        self.assertIn("Account created", texts)

    def test_timeline_includes_recovery_code_generation(self):
        RecoveryCode.generate_for(self.target)
        response = self.client.get(reverse("admin_user_detail", args=[self.target.id]))
        texts = [e['text'] for e in response.context["timeline"]]
        self.assertTrue(any("Recovery code generated" in t for t in texts))

    def test_timeline_includes_admin_actions(self):
        self.client.post(reverse("admin_user_detail", args=[self.target.id]), {"action": "warn_user", "warning": "test warning"})
        response = self.client.get(reverse("admin_user_detail", args=[self.target.id]))
        texts = [e['text'] for e in response.context["timeline"]]
        self.assertTrue(any("warn_user" in t for t in texts))

    def test_timeline_includes_recent_usage(self):
        UsageEvent.objects.create(user=self.target, provider="groq", model_id="cyber-max", event_type="chat")
        response = self.client.get(reverse("admin_user_detail", args=[self.target.id]))
        texts = [e['text'] for e in response.context["timeline"]]
        self.assertTrue(any("chat request" in t for t in texts))

    def test_timeline_is_sorted_newest_first(self):
        UsageEvent.objects.create(user=self.target, provider="groq", model_id="cyber-max", event_type="chat")
        response = self.client.get(reverse("admin_user_detail", args=[self.target.id]))
        timestamps = [e['at'] for e in response.context["timeline"]]
        self.assertEqual(timestamps, sorted(timestamps, reverse=True))


class WarnUserActionTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(username="admin", password="testpass123", email="a@example.com")
        self.client.force_login(self.superuser)
        self.target = User.objects.create_user(username="target", password="x")

    def test_warn_user_does_not_change_account_status(self):
        self.client.post(reverse("admin_user_detail", args=[self.target.id]), {"action": "warn_user", "warning": "be careful"})
        self.target.refresh_from_db()
        self.assertTrue(self.target.is_active)

    def test_warn_user_is_audit_logged(self):
        self.client.post(reverse("admin_user_detail", args=[self.target.id]), {"action": "warn_user", "warning": "be careful"})
        self.assertTrue(AdminAuditLog.objects.filter(action="warn_user", target_user=self.target, detail__icontains="be careful").exists())

    def test_blank_warning_is_not_logged(self):
        self.client.post(reverse("admin_user_detail", args=[self.target.id]), {"action": "warn_user", "warning": "   "})
        self.assertFalse(AdminAuditLog.objects.filter(action="warn_user", target_user=self.target).exists())


class GlobalSearchExtendedTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(username="admin", password="testpass123", email="a@example.com")
        self.client.force_login(self.superuser)

    def test_searches_audit_log(self):
        target = User.objects.create_user(username="target", password="x")
        AdminAuditLog.objects.create(actor=self.superuser, action="ban", target_user=target, detail="unique audit search marker")
        data = self.client.get(reverse("admin_quick_search"), {"q": "unique audit search marker"}).json()
        self.assertTrue(any("unique audit search marker" in a['detail'] for a in data['audit_log']))

    def test_searches_broadcasts(self):
        Broadcast.objects.create(message="unique broadcast search marker", active=False)
        data = self.client.get(reverse("admin_quick_search"), {"q": "unique broadcast search marker"}).json()
        self.assertTrue(any("unique broadcast search marker" in b['message'] for b in data['broadcasts']))
