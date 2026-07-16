"""Tests for chat/services/email.py - the hardened SMTP sender that fixed
the production-only worker-SIGKILL incident (see that module's docstring
for the full root-cause writeup). Every network call is mocked: the point
of these tests is proving each failure mode is caught, logged, and
degrades to EmailSendResult(False, ...) rather than raising or hanging -
not exercising a real SMTP server, which has no place in a test suite.
"""
import smtplib
import socket
import ssl
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from chat.models import PasswordResetOTP
from chat.services.email import EmailSendResult, log_email_configuration, send_otp_email

User = get_user_model()

SMTP_SETTINGS = dict(
    EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
    EMAIL_HOST="smtp.gmail.com",
    EMAIL_PORT=587,
    EMAIL_USE_TLS=True,
    EMAIL_USE_SSL=False,
    EMAIL_HOST_USER="bot@example.com",
    EMAIL_HOST_PASSWORD="app-password",
    EMAIL_TIMEOUT=10,
    DEFAULT_FROM_EMAIL="bot@example.com",
)


class EmailSendResultTests(TestCase):
    def test_result_is_a_plain_success_flag_and_message(self):
        ok = EmailSendResult(True)
        self.assertTrue(ok.success)
        self.assertEqual(ok.error, "")
        bad = EmailSendResult(False, "reason")
        self.assertFalse(bad.success)
        self.assertEqual(bad.error, "reason")


@override_settings(**SMTP_SETTINGS)
class SendOtpEmailSmtpPathTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="u", password="x", email="u@example.com")
        self.otp = PasswordResetOTP.generate_for(self.user)

    def _mock_addrinfo(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("142.250.1.1", 587))]

    @patch("chat.services.email.socket.getaddrinfo")
    @patch("chat.services.email.smtplib.SMTP")
    def test_happy_path_calls_every_stage_and_returns_success(self, mock_smtp_cls, mock_getaddrinfo):
        self._mock_addrinfo(mock_getaddrinfo)
        mock_conn = MagicMock()
        mock_smtp_cls.return_value = mock_conn

        result = send_otp_email(self.user, self.otp)

        self.assertTrue(result.success)
        mock_conn.starttls.assert_called_once()
        mock_conn.login.assert_called_once_with("bot@example.com", "app-password")
        mock_conn.sendmail.assert_called_once()
        mock_conn.quit.assert_called_once()

    @patch("chat.services.email.socket.getaddrinfo")
    def test_dns_failure_is_caught_and_reported(self, mock_getaddrinfo):
        mock_getaddrinfo.side_effect = socket.gaierror("Name or service not known")
        result = send_otp_email(self.user, self.otp)
        self.assertFalse(result.success)
        self.assertIn("DNS", result.error)

    @patch("chat.services.email.socket.getaddrinfo")
    @patch("chat.services.email.smtplib.SMTP")
    def test_tcp_connect_timeout_is_caught_not_raised(self, mock_smtp_cls, mock_getaddrinfo):
        # This is the exact production failure mode: the connection attempt
        # itself hangs/times out, before authentication is ever reached.
        self._mock_addrinfo(mock_getaddrinfo)
        mock_smtp_cls.side_effect = socket.timeout("timed out")

        result = send_otp_email(self.user, self.otp)

        self.assertFalse(result.success)
        self.assertIn("too long", result.error)

    @patch("chat.services.email.socket.getaddrinfo")
    @patch("chat.services.email.smtplib.SMTP")
    def test_connection_refused_is_caught(self, mock_smtp_cls, mock_getaddrinfo):
        self._mock_addrinfo(mock_getaddrinfo)
        mock_smtp_cls.side_effect = ConnectionRefusedError("refused")
        result = send_otp_email(self.user, self.otp)
        self.assertFalse(result.success)

    @patch("chat.services.email.socket.getaddrinfo")
    @patch("chat.services.email.smtplib.SMTP")
    def test_starttls_ssl_error_is_caught(self, mock_smtp_cls, mock_getaddrinfo):
        self._mock_addrinfo(mock_getaddrinfo)
        mock_conn = MagicMock()
        mock_conn.starttls.side_effect = ssl.SSLError("handshake failed")
        mock_smtp_cls.return_value = mock_conn

        result = send_otp_email(self.user, self.otp)

        self.assertFalse(result.success)
        mock_conn.quit.assert_called_once()  # still closed despite the failure

    @patch("chat.services.email.socket.getaddrinfo")
    @patch("chat.services.email.smtplib.SMTP")
    def test_auth_error_is_caught(self, mock_smtp_cls, mock_getaddrinfo):
        self._mock_addrinfo(mock_getaddrinfo)
        mock_conn = MagicMock()
        mock_conn.login.side_effect = smtplib.SMTPAuthenticationError(535, b"Authentication failed")
        mock_smtp_cls.return_value = mock_conn

        result = send_otp_email(self.user, self.otp)

        self.assertFalse(result.success)

    @patch("chat.services.email.socket.getaddrinfo")
    @patch("chat.services.email.smtplib.SMTP")
    def test_send_failure_is_caught(self, mock_smtp_cls, mock_getaddrinfo):
        self._mock_addrinfo(mock_getaddrinfo)
        mock_conn = MagicMock()
        mock_conn.sendmail.side_effect = smtplib.SMTPException("rejected")
        mock_smtp_cls.return_value = mock_conn

        result = send_otp_email(self.user, self.otp)

        self.assertFalse(result.success)
        mock_conn.quit.assert_called_once()

    @patch("chat.services.email.socket.getaddrinfo")
    @patch("chat.services.email.smtplib.SMTP")
    def test_connection_is_always_closed_even_on_quit_failure(self, mock_smtp_cls, mock_getaddrinfo):
        # quit() itself raising (e.g. the socket is already dead, which is
        # often exactly why we're in the failure path) must not mask the
        # original error or blow up the whole call.
        self._mock_addrinfo(mock_getaddrinfo)
        mock_conn = MagicMock()
        mock_conn.login.side_effect = smtplib.SMTPAuthenticationError(535, b"bad creds")
        mock_conn.quit.side_effect = OSError("already closed")
        mock_smtp_cls.return_value = mock_conn

        result = send_otp_email(self.user, self.otp)

        self.assertFalse(result.success)
        mock_conn.close.assert_called_once()

    @patch("chat.services.email.socket.getaddrinfo")
    def test_dns_lookup_forces_ipv4(self, mock_getaddrinfo):
        mock_getaddrinfo.side_effect = socket.gaierror("boom")
        send_otp_email(self.user, self.otp)
        args, kwargs = mock_getaddrinfo.call_args
        self.assertEqual(args[2], socket.AF_INET)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend")
class SendOtpEmailConsoleBackendTests(TestCase):
    def test_console_backend_delegates_to_django_and_succeeds(self):
        user = User.objects.create_user(username="u2", password="x", email="u2@example.com")
        otp = PasswordResetOTP.generate_for(user)
        result = send_otp_email(user, otp)
        self.assertTrue(result.success)


class LogEmailConfigurationTests(TestCase):
    @override_settings(EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend")
    def test_warns_on_console_backend(self):
        with self.assertLogs("chat.services.email", level="WARNING") as logs:
            log_email_configuration()
        self.assertTrue(any("console backend" in m for m in logs.output))

    @override_settings(**SMTP_SETTINGS)
    def test_no_warning_for_smtp_backend(self):
        with self.assertLogs("chat.services.email", level="INFO") as logs:
            log_email_configuration()
        self.assertFalse(any(r.levelname == "WARNING" for r in logs.records))

    def test_never_logs_the_password(self):
        with self.assertLogs("chat.services.email", level="INFO") as logs:
            with override_settings(**SMTP_SETTINGS):
                log_email_configuration()
        joined = " ".join(logs.output)
        self.assertNotIn("app-password", joined)
