"""Tests for the Role-Based Access Control system (chat/permissions.py,
chat/models.py's Role, and the RBAC-aware parts of chat/admin_views.py,
chat/middleware.py, chat/signals.py). Kept separate from
chat/test_admin_console*.py since this is specifically the permission
*mechanism*, not the console's individual features."""
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse

from chat.models import Role, UserProfile
from chat.permissions import (
    can_access_admin_console, can_act_on_target, has_permission,
    has_role_at_least, is_owner, role_level, sync_django_flags, user_role,
)

User = get_user_model()


class RoleHierarchyTests(TestCase):
    def test_ordering_is_strictly_descending(self):
        ordered = [Role.OWNER, Role.SUPER_ADMIN, Role.ADMIN, Role.MODERATOR, Role.VERIFIED, Role.USER]
        levels = [role_level(r) for r in ordered]
        self.assertEqual(levels, sorted(levels, reverse=True))

    def test_has_role_at_least_is_inclusive(self):
        user = User.objects.create_user(username="u", password="x")
        UserProfile.objects.create(user=user, role=Role.ADMIN)
        self.assertTrue(has_role_at_least(user, Role.ADMIN))
        self.assertTrue(has_role_at_least(user, Role.MODERATOR))
        self.assertFalse(has_role_at_least(user, Role.SUPER_ADMIN))

    def test_anonymous_user_resolves_to_user_role(self):
        from django.contrib.auth.models import AnonymousUser
        self.assertEqual(user_role(AnonymousUser()), Role.USER)
        self.assertFalse(has_role_at_least(AnonymousUser(), Role.VERIFIED))

    def test_user_with_no_profile_falls_back_to_django_flags(self):
        # The chicken-and-egg case: a freshly createsuperuser()'d account
        # has no UserProfile row yet, but must still resolve to an
        # admin-tier role rather than Role.USER, or they'd be locked out of
        # the very console that would let them fix it.
        su = User.objects.create_superuser(username="su", password="x", email="su@example.com")
        self.assertFalse(UserProfile.objects.filter(user=su).exists())
        self.assertEqual(user_role(su), Role.SUPER_ADMIN)
        self.assertTrue(can_access_admin_console(su))

        staff = User.objects.create_user(username="staff", password="x", is_staff=True)
        self.assertEqual(user_role(staff), Role.ADMIN)

        plain = User.objects.create_user(username="plain", password="x")
        self.assertEqual(user_role(plain), Role.USER)

    def test_moderator_cannot_access_admin_console(self):
        mod = User.objects.create_user(username="mod", password="x")
        UserProfile.objects.create(user=mod, role=Role.MODERATOR)
        self.assertFalse(can_access_admin_console(mod))
        self.assertTrue(has_permission(mod, "ban_user"))
        self.assertFalse(has_permission(mod, "manage_feature_flags"))


class RequireRoleDecoratorTests(TestCase):
    """Exercises the decorator through a real admin-console view rather than
    a synthetic one, since that's the only way it's actually used."""

    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="testpass123", email="owner@example.com")
        UserProfile.objects.create(user=self.owner, role=Role.OWNER)
        self.admin = User.objects.create_user(username="admin", password="testpass123", email="admin@example.com")
        UserProfile.objects.create(user=self.admin, role=Role.ADMIN)
        self.moderator = User.objects.create_user(username="moderator", password="testpass123", email="moderator@example.com")
        UserProfile.objects.create(user=self.moderator, role=Role.MODERATOR)
        self.plain = User.objects.create_user(username="plain", password="testpass123", email="plain@example.com")
        UserProfile.objects.create(user=self.plain, role=Role.USER)

    def test_owner_admin_super_admin_can_reach_console(self):
        for username in ("owner", "admin"):
            client = Client()
            client.login(username=username, password="testpass123")
            response = client.get(reverse("admin_dashboard"))
            self.assertEqual(response.status_code, 200, f"{username} should reach the dashboard")

    def test_moderator_gets_403_not_redirect(self):
        client = Client()
        client.login(username="moderator", password="testpass123")
        response = client.get(reverse("admin_dashboard"))
        self.assertEqual(response.status_code, 403)

    def test_plain_user_gets_403(self):
        client = Client()
        client.login(username="plain", password="testpass123")
        response = client.get(reverse("admin_dashboard"))
        self.assertEqual(response.status_code, 403)

    def test_anonymous_user_redirected_to_login_not_403(self):
        client = Client()
        response = client.get(reverse("admin_dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_every_admin_console_url_enforces_role(self):
        client = Client()
        client.login(username="plain", password="testpass123")
        urls = [
            reverse("admin_dashboard"), reverse("admin_users_list"),
            reverse("admin_user_detail", args=[self.admin.id]),
            reverse("admin_audit_log"), reverse("admin_security"),
            reverse("admin_feature_flags"), reverse("admin_broadcasts"),
            reverse("admin_export_user_data", args=[self.admin.id]),
        ]
        for url in urls:
            response = client.get(url)
            self.assertEqual(response.status_code, 403, f"{url} did not enforce role >= Admin")


class OwnerProtectionTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="testpass123", email="owner@example.com")
        UserProfile.objects.create(user=self.owner, role=Role.OWNER)
        self.super_admin = User.objects.create_user(username="superadmin", password="testpass123", email="sa@example.com")
        UserProfile.objects.create(user=self.super_admin, role=Role.SUPER_ADMIN)
        self.client_super_admin = Client()
        self.client_super_admin.login(username="superadmin", password="testpass123")

    def test_super_admin_cannot_ban_owner(self):
        response = self.client_super_admin.post(
            reverse("admin_user_detail", args=[self.owner.id]), {"action": "ban", "reason": "test"}
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(UserProfile.objects.get(user=self.owner).is_banned)

    def test_super_admin_cannot_delete_owner(self):
        response = self.client_super_admin.post(
            reverse("admin_user_detail", args=[self.owner.id]), {"action": "delete_account"}
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(UserProfile.objects.get(user=self.owner).is_deleted)

    def test_super_admin_cannot_change_owner_role(self):
        response = self.client_super_admin.post(
            reverse("admin_user_detail", args=[self.owner.id]), {"action": "change_role", "role": "admin"}
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(UserProfile.objects.get(user=self.owner).role, Role.OWNER)

    def test_super_admin_cannot_transfer_ownership(self):
        response = self.client_super_admin.post(
            reverse("admin_user_detail", args=[self.owner.id]), {"action": "transfer_ownership"}
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(UserProfile.objects.get(user=self.owner).role, Role.OWNER)

    def test_owner_cannot_change_own_role_via_generic_dropdown(self):
        client = Client()
        client.login(username="owner", password="testpass123")
        response = client.post(
            reverse("admin_user_detail", args=[self.owner.id]), {"action": "change_role", "role": "super_admin"}
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(UserProfile.objects.get(user=self.owner).role, Role.OWNER)

    def test_can_act_on_target_helper(self):
        self.assertFalse(can_act_on_target(self.super_admin, self.owner))
        self.assertTrue(can_act_on_target(self.owner, self.owner))
        self.assertTrue(can_act_on_target(self.super_admin, self.super_admin))


class OwnershipTransferTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="testpass123", email="owner@example.com")
        UserProfile.objects.create(user=self.owner, role=Role.OWNER)
        self.successor = User.objects.create_user(username="successor", password="testpass123", email="successor@example.com")
        UserProfile.objects.create(user=self.successor, role=Role.ADMIN)
        self.client = Client()
        self.client.login(username="owner", password="testpass123")

    def test_transfer_makes_exactly_one_new_owner(self):
        self.client.post(reverse("admin_user_detail", args=[self.successor.id]), {"action": "transfer_ownership"})
        self.assertEqual(UserProfile.objects.get(user=self.successor).role, Role.OWNER)
        self.assertEqual(UserProfile.objects.get(user=self.owner).role, Role.SUPER_ADMIN)
        self.assertEqual(UserProfile.objects.filter(role=Role.OWNER).count(), 1)

    def test_transfer_syncs_django_flags_for_both_accounts(self):
        self.client.post(reverse("admin_user_detail", args=[self.successor.id]), {"action": "transfer_ownership"})
        self.successor.refresh_from_db()
        self.owner.refresh_from_db()
        self.assertTrue(self.successor.is_superuser)
        self.assertTrue(self.owner.is_superuser)  # Super Admin still syncs to is_superuser=True

    def test_non_owner_cannot_transfer(self):
        other = User.objects.create_user(username="other", password="testpass123", email="other@example.com")
        UserProfile.objects.create(user=other, role=Role.SUPER_ADMIN)
        client = Client()
        client.login(username="other", password="testpass123")
        response = client.post(reverse("admin_user_detail", args=[self.successor.id]), {"action": "transfer_ownership"})
        self.assertEqual(response.status_code, 403)

    def test_cannot_transfer_to_self(self):
        response = self.client.post(reverse("admin_user_detail", args=[self.owner.id]), {"action": "transfer_ownership"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(UserProfile.objects.get(user=self.owner).role, Role.OWNER)

    def test_transfer_is_audit_logged(self):
        from chat.models import AdminAuditLog
        self.client.post(reverse("admin_user_detail", args=[self.successor.id]), {"action": "transfer_ownership"})
        self.assertTrue(AdminAuditLog.objects.filter(action="ownership_transfer", target_user=self.successor).exists())


class SyncDjangoFlagsTests(TestCase):
    def test_admin_and_above_become_staff(self):
        for role in (Role.OWNER, Role.SUPER_ADMIN, Role.ADMIN, Role.MODERATOR):
            user = User.objects.create_user(username=f"u_{role}", password="x")
            sync_django_flags(user, role)
            user.refresh_from_db()
            self.assertTrue(user.is_staff, f"{role} should be is_staff")

    def test_only_super_admin_and_owner_become_superuser(self):
        for role in (Role.OWNER, Role.SUPER_ADMIN):
            user = User.objects.create_user(username=f"su_{role}", password="x")
            sync_django_flags(user, role)
            user.refresh_from_db()
            self.assertTrue(user.is_superuser, f"{role} should be is_superuser")
        for role in (Role.ADMIN, Role.MODERATOR, Role.VERIFIED, Role.USER):
            user = User.objects.create_user(username=f"nsu_{role}", password="x")
            sync_django_flags(user, role)
            user.refresh_from_db()
            self.assertFalse(user.is_superuser, f"{role} should not be is_superuser")


class VerifiedRoleAutoPromotionTests(TestCase):
    def test_email_confirmation_promotes_user_to_verified(self):
        from allauth.account.models import EmailAddress
        from allauth.account.signals import email_confirmed

        user = User.objects.create_user(username="newbie", password="x", email="newbie@example.com")
        UserProfile.objects.create(user=user, role=Role.USER)
        email_address = EmailAddress.objects.create(user=user, email="newbie@example.com", verified=True, primary=True)

        email_confirmed.send(sender=None, request=None, email_address=email_address)

        self.assertEqual(UserProfile.objects.get(user=user).role, Role.VERIFIED)

    def test_email_confirmation_never_downgrades_a_higher_role(self):
        from allauth.account.models import EmailAddress
        from allauth.account.signals import email_confirmed

        admin = User.objects.create_user(username="adminconfirm", password="x", email="adminconfirm@example.com")
        UserProfile.objects.create(user=admin, role=Role.ADMIN)
        email_address = EmailAddress.objects.create(user=admin, email="adminconfirm@example.com", verified=True, primary=True)

        email_confirmed.send(sender=None, request=None, email_address=email_address)

        self.assertEqual(UserProfile.objects.get(user=admin).role, Role.ADMIN)


class AdminConsoleLinkVisibilityTests(TestCase):
    def test_admin_console_link_shown_for_admin(self):
        admin = User.objects.create_user(username="linkadmin", password="testpass123", email="linkadmin@example.com")
        UserProfile.objects.create(user=admin, role=Role.ADMIN)
        client = Client()
        client.login(username="linkadmin", password="testpass123")
        response = client.get(reverse("home"))
        self.assertContains(response, "ADMIN CONSOLE")

    def test_admin_console_link_hidden_for_plain_user(self):
        user = User.objects.create_user(username="linkuser", password="testpass123", email="linkuser@example.com")
        UserProfile.objects.create(user=user, role=Role.USER)
        client = Client()
        client.login(username="linkuser", password="testpass123")
        response = client.get(reverse("home"))
        self.assertNotContains(response, "ADMIN CONSOLE")

    def test_admin_console_link_hidden_for_moderator(self):
        mod = User.objects.create_user(username="linkmod", password="testpass123", email="linkmod@example.com")
        UserProfile.objects.create(user=mod, role=Role.MODERATOR)
        client = Client()
        client.login(username="linkmod", password="testpass123")
        response = client.get(reverse("home"))
        self.assertNotContains(response, "ADMIN CONSOLE")


class MaintenanceModeRoleBypassTests(TestCase):
    def test_admin_bypasses_maintenance_even_without_is_superuser(self):
        from chat.models import FeatureFlag
        FeatureFlag.objects.filter(key="maintenance_mode").update(enabled=True)
        # Fetch through save() so the cache invalidates (queryset.update()
        # bypasses FeatureFlag.save()'s cache-clear, same caveat as
        # elsewhere in this test suite).
        flag = FeatureFlag.objects.get(key="maintenance_mode")
        flag.enabled = True
        flag.save(update_fields=["enabled"])

        admin = User.objects.create_user(username="mmadmin", password="testpass123", email="mmadmin@example.com")
        UserProfile.objects.create(user=admin, role=Role.ADMIN)  # is_staff/is_superuser NOT set
        client = Client()
        client.login(username="mmadmin", password="testpass123")
        response = client.get(reverse("home"))
        self.assertNotEqual(response.status_code, 503)

        flag.enabled = False
        flag.save(update_fields=["enabled"])
