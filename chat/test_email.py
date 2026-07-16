"""Tests for the Resend-based email system that replaced Gmail SMTP
(chat/services/resend_backend.py + chat/services/email.py). SMTP could not
be tuned into working from Render at all (OSError: [Errno 101] Network is
unreachable - a routing restriction, not a timeout), so it was removed
entirely in favor of Resend's HTTPS API.

Every network call is mocked: the point of these tests is proving retry/
backoff behavior, that failures always degrade to a logged EmailSendResult
rather than raising, and that the API key is never logged - not exercising
a real Resend account, which has no place in a test suite. time.sleep is
patched out everywhere retries are exercised so these tests stay fast.
"""
from unittest.mock import MagicMock, patch

import requests
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from chat.models import PasswordResetOTP
from chat.services.email import EmailSendResult, log_email_configuration, send_html_email, send_otp_email
from chat.services.resend_backend import ResendEmailBackend, _build_payload

User = get_user_model()

RESEND_SETTINGS = dict(
    EMAIL_BACKEND="chat.services.resend_backend.ResendEmailBackend",
    RESEND_API_KEY="re_test_key_123",
    DEFAULT_FROM_EMAIL="noreply@example.com",
)


def _response(status_code, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    return resp


@override_settings(**RESEND_SETTINGS)
class ResendEmailBackendTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="u", password="x", email="u@example.com")
        self.otp = PasswordResetOTP.generate_for(self.user)

    @patch("chat.services.resend_backend.time.sleep")
    @patch("chat.services.resend_backend.requests.post")
    def test_success_on_first_attempt_no_retry(self, mock_post, mock_sleep):
        mock_post.return_value = _response(200)
        result = send_otp_email(self.user, self.otp)
        self.assertTrue(result.success)
        self.assertEqual(mock_post.call_count, 1)
        mock_sleep.assert_not_called()

    @patch("chat.services.resend_backend.time.sleep")
    @patch("chat.services.resend_backend.requests.post")
    def test_missing_api_key_skips_send_without_network_call(self, mock_post, mock_sleep):
        with override_settings(RESEND_API_KEY=""):
            result = send_otp_email(self.user, self.otp)
        self.assertFalse(result.success)
        mock_post.assert_not_called()

    @patch("chat.services.resend_backend.time.sleep")
    @patch("chat.services.resend_backend.requests.post")
    def test_retryable_5xx_then_success(self, mock_post, mock_sleep):
        mock_post.side_effect = [_response(500), _response(200)]
        result = send_otp_email(self.user, self.otp)
        self.assertTrue(result.success)
        self.assertEqual(mock_post.call_count, 2)
        self.assertEqual(mock_sleep.call_count, 1)

    @patch("chat.services.resend_backend.time.sleep")
    @patch("chat.services.resend_backend.requests.post")
    def test_retryable_429_exhausts_max_three_attempts_then_fails(self, mock_post, mock_sleep):
        mock_post.return_value = _response(429, "rate limited")
        result = send_otp_email(self.user, self.otp)
        self.assertFalse(result.success)
        self.assertEqual(mock_post.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)  # backoff between attempts, not after the last

    @patch("chat.services.resend_backend.time.sleep")
    @patch("chat.services.resend_backend.requests.post")
    def test_non_retryable_401_fails_immediately_without_retrying(self, mock_post, mock_sleep):
        mock_post.return_value = _response(401, "invalid api key")
        result = send_otp_email(self.user, self.otp)
        self.assertFalse(result.success)
        self.assertEqual(mock_post.call_count, 1)
        mock_sleep.assert_not_called()

    @patch("chat.services.resend_backend.time.sleep")
    @patch("chat.services.resend_backend.requests.post")
    def test_network_exception_is_retried_then_can_succeed(self, mock_post, mock_sleep):
        mock_post.side_effect = [requests.exceptions.ConnectionError("refused"), _response(200)]
        result = send_otp_email(self.user, self.otp)
        self.assertTrue(result.success)
        self.assertEqual(mock_post.call_count, 2)

    @patch("chat.services.resend_backend.time.sleep")
    @patch("chat.services.resend_backend.requests.post")
    def test_persistent_network_exception_exhausts_retries_and_fails_gracefully(self, mock_post, mock_sleep):
        mock_post.side_effect = requests.exceptions.Timeout("timed out")
        result = send_otp_email(self.user, self.otp)
        self.assertFalse(result.success)
        self.assertEqual(mock_post.call_count, 3)

    @patch("chat.services.resend_backend.requests.post")
    def test_never_raises_even_with_fail_silently_false(self, mock_post):
        mock_post.side_effect = requests.exceptions.Timeout("timed out")
        with patch("chat.services.resend_backend.time.sleep"):
            # send_mail defaults to fail_silently=False; the backend must
            # still never let an exception escape to the caller.
            from django.core.mail import send_mail
            sent = send_mail("subj", "body", "from@example.com", ["to@example.com"], fail_silently=False)
        self.assertEqual(sent, 0)

    @patch("chat.services.resend_backend.time.sleep")
    @patch("chat.services.resend_backend.requests.post")
    def test_api_key_is_never_logged(self, mock_post, mock_sleep):
        mock_post.return_value = _response(401, "invalid api key")
        with self.assertLogs("chat.services.resend_backend", level="WARNING") as logs:
            send_otp_email(self.user, self.otp)
        joined = " ".join(logs.output)
        self.assertNotIn("re_test_key_123", joined)

    @patch("chat.services.resend_backend.requests.post")
    def test_html_email_payload_includes_both_text_and_html(self, mock_post):
        mock_post.return_value = _response(200)
        send_html_email("to@example.com", "Welcome", "plain text", html_body="<p>html</p>")
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["text"], "plain text")
        self.assertEqual(payload["html"], "<p>html</p>")
        self.assertEqual(payload["to"], ["to@example.com"])

    @patch("chat.services.resend_backend.requests.post")
    def test_plain_text_only_email_has_no_html_key(self, mock_post):
        mock_post.return_value = _response(200)
        send_html_email("to@example.com", "Subject", "plain only")
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["text"], "plain only")
        self.assertNotIn("html", payload)

    def test_backend_send_messages_returns_zero_for_empty_list(self):
        self.assertEqual(ResendEmailBackend().send_messages([]), 0)


class BuildPayloadTests(TestCase):
    def test_maps_email_message_fields_onto_resend_shape(self):
        from django.core.mail import EmailMessage
        msg = EmailMessage(
            subject="Hi", body="Body text", from_email="from@example.com",
            to=["a@example.com"], cc=["b@example.com"], bcc=["c@example.com"],
            reply_to=["reply@example.com"],
        )
        payload = _build_payload(msg)
        self.assertEqual(payload["from"], "from@example.com")
        self.assertEqual(payload["to"], ["a@example.com"])
        self.assertEqual(payload["cc"], ["b@example.com"])
        self.assertEqual(payload["bcc"], ["c@example.com"])
        self.assertEqual(payload["reply_to"], ["reply@example.com"])
        self.assertEqual(payload["text"], "Body text")


@override_settings(EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend")
class ConsoleBackendFallbackTests(TestCase):
    def test_console_backend_still_works_for_local_debugging(self):
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

    @override_settings(EMAIL_BACKEND="chat.services.resend_backend.ResendEmailBackend", RESEND_API_KEY="")
    def test_warns_when_resend_backend_but_no_api_key(self):
        with self.assertLogs("chat.services.email", level="WARNING") as logs:
            log_email_configuration()
        self.assertTrue(any("RESEND_API_KEY is not set" in m for m in logs.output))

    @override_settings(**RESEND_SETTINGS)
    def test_no_warning_when_resend_backend_and_key_present(self):
        with self.assertLogs("chat.services.email", level="INFO") as logs:
            log_email_configuration()
        self.assertFalse(any(r.levelname == "WARNING" for r in logs.records))

    @override_settings(**RESEND_SETTINGS)
    def test_never_logs_the_api_key(self):
        with self.assertLogs("chat.services.email", level="INFO") as logs:
            log_email_configuration()
        joined = " ".join(logs.output)
        self.assertNotIn("re_test_key_123", joined)


class EmailSendResultTests(TestCase):
    def test_result_is_a_plain_success_flag_and_message(self):
        ok = EmailSendResult(True)
        self.assertTrue(ok.success)
        self.assertEqual(ok.error, "")
        bad = EmailSendResult(False, "reason")
        self.assertFalse(bad.success)
        self.assertEqual(bad.error, "reason")
