"""Tests for the authentication-platform upgrade: the Google account-merge
fix, session-tracking/management (UserSession), the email-verification
resend cooldown, and the login signal's UA-parsing + UserProfile snapshot.
Kept separate from chat/test_admin_console.py (admin-facing) and
chat/tests.py (core chat) since this is specifically the self-service auth
surface."""
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from allauth.account.models import EmailAddress, EmailConfirmation

from chat.models import SecurityEvent, UserProfile, UserSession
from chat.signals import record_google_link
from chat.utils.device import parse_client_info

User = get_user_model()


class GoogleAccountMergeConfigTests(TestCase):
    """The actual OAuth handshake isn't exercised here (that's allauth's own
    well-tested internals) - this locks in the specific configuration that
    was previously broken: EMAIL_AUTHENTICATION_AUTO_CONNECT alone did
    nothing without EMAIL_AUTHENTICATION also being true for the provider."""

    def test_google_provider_trusts_verified_email(self):
        from django.conf import settings
        google_settings = settings.SOCIALACCOUNT_PROVIDERS["google"]
        self.assertTrue(google_settings.get("EMAIL_AUTHENTICATION"))

    def test_auto_connect_is_enabled(self):
        from django.conf import settings
        self.assertTrue(settings.SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT)


class GoogleLinkSignalTests(TestCase):
    """Exercises chat/signals.py's record_google_link directly with a
    lightweight stand-in for allauth's SocialLogin/SocialAccount, rather than
    driving a full OAuth handshake - this is the app's own logic being
    tested, not allauth's."""

    def _fire(self, user, avatar_url="https://lh3.googleusercontent.com/a/pic.jpg", provider="google"):
        account = SimpleNamespace(provider=provider, get_avatar_url=lambda: avatar_url)
        sociallogin = SimpleNamespace(account=account, user=user)
        record_google_link(sender=None, request=None, sociallogin=sociallogin)

    def test_fresh_signup_gets_google_source_and_avatar(self):
        user = User.objects.create_user(username="newgoogle", email="newgoogle@example.com")
        self._fire(user)
        profile = UserProfile.objects.get(user=user)
        self.assertEqual(profile.registration_source, "google")
        self.assertEqual(profile.avatar_url, "https://lh3.googleusercontent.com/a/pic.jpg")

    def test_existing_user_connecting_google_keeps_original_source(self):
        user = User.objects.create_user(username="oldemail", email="oldemail@example.com")
        UserProfile.objects.create(user=user, registration_source="email")
        user.date_joined = timezone.now() - timedelta(days=30)
        user.save(update_fields=["date_joined"])

        self._fire(user)

        profile = UserProfile.objects.get(user=user)
        self.assertEqual(profile.registration_source, "email")
        self.assertEqual(profile.avatar_url, "https://lh3.googleusercontent.com/a/pic.jpg")

    def test_non_google_provider_ignored(self):
        user = User.objects.create_user(username="other", email="other@example.com")
        self._fire(user, provider="github")
        self.assertFalse(UserProfile.objects.filter(user=user).exists())


class DeviceParsingResilienceTests(TestCase):
    """chat/utils/device.py's parse_client_info() feeds NOT NULL database
    columns on every login (including from mobile browsers and proxies that
    send minimal/malformed User-Agent headers) - it must be impossible for
    it to return a falsy value or raise, regardless of input."""

    def test_empty_string_falls_back_to_unknowns(self):
        browser, device, os_name = parse_client_info("")
        self.assertEqual(browser, "Unknown Browser")
        self.assertEqual(device, "Unknown Device")
        self.assertEqual(os_name, "Unknown OS")

    def test_none_input_falls_back_to_unknowns(self):
        browser, device, os_name = parse_client_info(None)
        self.assertEqual(browser, "Unknown Browser")
        self.assertEqual(device, "Unknown Device")
        self.assertEqual(os_name, "Unknown OS")

    def test_garbage_string_never_raises_and_never_returns_falsy(self):
        for garbage in ["a", "!!!", "\x00\x01\x02", "x" * 5000, "curl/7.0", "-", " "]:
            browser, device, os_name = parse_client_info(garbage)
            self.assertTrue(browser)
            self.assertTrue(device)
            self.assertTrue(os_name)

    @patch("chat.utils.device.parse_user_agent", side_effect=RuntimeError("parser exploded"))
    def test_underlying_parser_exception_is_caught(self, _mock):
        browser, device, os_name = parse_client_info("Mozilla/5.0 anything")
        self.assertEqual(browser, "Unknown Browser")
        self.assertEqual(device, "Unknown Device")
        self.assertEqual(os_name, "Unknown OS")

    def test_real_mobile_and_desktop_user_agents(self):
        android = parse_client_info(
            "Mozilla/5.0 (Linux; Android 14; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Mobile Safari/537.36"
        )
        self.assertIn("Chrome", android[0])
        # The library returns the specific detected model (e.g. "Samsung
        # SM-G991B") when it recognizes one, rather than a generic "Mobile" -
        # this test only needs a non-empty, non-"Unknown" value here.
        self.assertTrue(android[1])
        self.assertNotEqual(android[1], "Unknown Device")
        self.assertIn("Android", android[2])

        iphone = parse_client_info(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
        )
        self.assertEqual(iphone[1], "iPhone")
        self.assertIn("iOS", iphone[2])


class LoginNeverBlockedBySecurityLoggingTests(TestCase):
    """The literal bug report this fixes: a security-logging failure (of any
    kind - a NOT NULL violation, a network hiccup, whatever) must never turn
    into a failed login. These tests force failures at each write inside the
    signal and confirm the user still ends up authenticated."""

    def setUp(self):
        self.user = User.objects.create_user(username="resilient", password="testpass123", email="resilient@example.com")

    def test_login_succeeds_even_if_security_event_create_raises(self):
        with patch("chat.signals.SecurityEvent.objects.create", side_effect=Exception("simulated NOT NULL violation")):
            client = Client()
            response = client.post(reverse("account_login"), {"login": "resilient@example.com", "password": "testpass123"})
        self.assertTrue(response.wsgi_request.user.is_authenticated or "_auth_user_id" in client.session)

    def test_login_succeeds_even_if_profile_snapshot_raises(self):
        with patch("chat.signals.UserProfile.objects.get_or_create", side_effect=Exception("simulated DB error")):
            client = Client()
            response = client.post(reverse("account_login"), {"login": "resilient@example.com", "password": "testpass123"})
        self.assertIn("_auth_user_id", client.session)

    def test_login_succeeds_with_no_user_agent_header(self):
        client = Client(HTTP_USER_AGENT="")
        response = client.post(reverse("account_login"), {"login": "resilient@example.com", "password": "testpass123"})
        self.assertIn("_auth_user_id", client.session)
        event = SecurityEvent.objects.filter(user=self.user, event_type="login").first()
        self.assertIsNotNone(event)
        self.assertEqual(event.browser, "Unknown Browser")
        self.assertEqual(event.device, "Unknown Device")
        self.assertEqual(event.os, "Unknown OS")


class LoginSignalTrackingTests(TestCase):
    """Confirms a real login (via the Django test Client, which drives
    Django's own login()/user_logged_in signal exactly like production)
    populates the parsed browser/device fields, the UserProfile snapshot,
    and a UserSession row."""

    def setUp(self):
        self.user = User.objects.create_user(username="loginuser", password="testpass123", email="loginuser@example.com")

    def test_login_populates_security_event_and_profile_snapshot(self):
        client = Client(HTTP_USER_AGENT="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36")
        client.post(reverse("account_login"), {"login": "loginuser@example.com", "password": "testpass123"})

        event = SecurityEvent.objects.filter(user=self.user, event_type="login").first()
        self.assertIsNotNone(event)
        self.assertIn("Chrome", event.browser)
        self.assertEqual(event.device, "Desktop")
        self.assertIn("Windows", event.os)

        profile = UserProfile.objects.get(user=self.user)
        self.assertIn("Chrome", profile.last_login_browser)
        self.assertEqual(profile.last_login_device, "Desktop")
        self.assertIn("Windows", profile.last_login_os)

    def test_login_creates_user_session(self):
        client = Client(HTTP_USER_AGENT="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36")
        client.post(reverse("account_login"), {"login": "loginuser@example.com", "password": "testpass123"})

        session_key = client.session.session_key
        user_session = UserSession.objects.filter(user=self.user, session_key=session_key).first()
        self.assertIsNotNone(user_session)
        self.assertIn("Chrome", user_session.browser)


class SessionManagementViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="devices", password="testpass123", email="devices@example.com")
        self.client = Client(HTTP_USER_AGENT="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36")
        self.client.post(reverse("account_login"), {"login": "devices@example.com", "password": "testpass123"})

    def test_logout_one_session_removes_it_and_kills_django_session(self):
        # A second "device" logging in under a separate client.
        other_client = Client(HTTP_USER_AGENT="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Safari/604.1")
        other_client.post(reverse("account_login"), {"login": "devices@example.com", "password": "testpass123"})
        other_session_key = other_client.session.session_key
        other_user_session = UserSession.objects.get(user=self.user, session_key=other_session_key)

        response = self.client.post(reverse("logout_session", args=[other_user_session.id]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(UserSession.objects.filter(id=other_user_session.id).exists())
        self.assertFalse(Session.objects.filter(session_key=other_session_key).exists())

    def test_cannot_logout_another_users_session(self):
        stranger = User.objects.create_user(username="stranger", password="testpass123", email="stranger@example.com")
        stranger_client = Client(HTTP_USER_AGENT="Mozilla/5.0")
        stranger_client.post(reverse("account_login"), {"login": "stranger@example.com", "password": "testpass123"})
        stranger_session = UserSession.objects.get(user=stranger)

        response = self.client.post(reverse("logout_session", args=[stranger_session.id]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(UserSession.objects.filter(id=stranger_session.id).exists())

    def test_logout_all_sessions_removes_every_session(self):
        other_client = Client(HTTP_USER_AGENT="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Safari/604.1")
        other_client.post(reverse("account_login"), {"login": "devices@example.com", "password": "testpass123"})
        self.assertEqual(UserSession.objects.filter(user=self.user).count(), 2)

        response = self.client.post(reverse("logout_all_sessions"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(UserSession.objects.filter(user=self.user).count(), 0)


class VerificationResendCooldownTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="verifyme", password="testpass123", email="verifyme@example.com")
        self.email_address = EmailAddress.objects.create(user=self.user, email="verifyme@example.com", primary=True, verified=False)
        self.client = Client()
        self.client.force_login(self.user)

    @patch("chat.views.verification_required", return_value=True)
    def test_second_resend_within_cooldown_is_rejected(self, _mock):
        EmailConfirmation.objects.create(email_address=self.email_address, key="k1", sent=timezone.now())
        response = self.client.post(reverse("resend_verification_email"))
        self.assertEqual(response.status_code, 429)
        self.assertIn("wait", response.json()["error"].lower())

    @patch("chat.views.verification_required", return_value=True)
    def test_resend_after_cooldown_expires_succeeds(self, _mock):
        EmailConfirmation.objects.create(
            email_address=self.email_address, key="k1",
            sent=timezone.now() - timedelta(seconds=60),
        )
        response = self.client.post(reverse("resend_verification_email"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "sent")


class EmailVerifiedTimestampTests(TestCase):
    def test_email_confirmed_signal_sets_verified_at(self):
        from allauth.account.signals import email_confirmed
        user = User.objects.create_user(username="confirmee", password="testpass123", email="confirmee@example.com")
        email_address = EmailAddress.objects.create(user=user, email="confirmee@example.com", primary=True, verified=True)

        email_confirmed.send(sender=None, request=None, email_address=email_address)

        profile = UserProfile.objects.get(user=user)
        self.assertIsNotNone(profile.email_verified_at)
