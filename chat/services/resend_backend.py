"""Custom Django email backend that sends via the Resend HTTP API
(https://resend.com/docs/api-reference/emails/send-email) instead of SMTP.

Why a backend rather than a one-off helper function: Django's own mail
plumbing (django.core.mail.send_mail, EmailMessage, EmailMultiAlternatives)
- and critically, django-allauth's OWN signup-confirmation and password-
reset-by-link emails, which allauth's adapter sends internally and which
this project's own code never touches directly - all funnel through
whatever EMAIL_BACKEND is configured. Pointing EMAIL_BACKEND at this class
migrates every one of those call sites to Resend automatically, with zero
changes needed to chat/adapters.py or any view.

Why Resend instead of tuning SMTP further: Render's outbound network
cannot reach smtp.gmail.com at all (OSError: [Errno 101] Network is
unreachable - a routing/firewall restriction, not a slow-DNS or credentials
problem), so no amount of SMTP timeout/retry tuning could ever fix it.
Resend's HTTPS API travels over the same outbound path this app already
uses for Groq/Mistral/Tavily, which demonstrably does work from Render.

Deliberately never raises, regardless of the caller's fail_silently value:
this migration's hard requirement is that a failed email must never crash
a request - signup, password reset, and admin actions must all keep
working even if Resend is down, rate-limiting, or misconfigured. So
failures here always degrade to "0 messages sent, fully logged", never a
propagated exception. This is a deliberate, documented deviation from
BaseEmailBackend's normal contract (where fail_silently=False lets
exceptions propagate) - not an oversight.
"""
import logging
import time

import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"

# Each individual HTTP attempt's ceiling - deliberately short (Render Free
# has limited resources; a hung request should never tie up a worker for
# long) and well within gunicorn's --timeout (see Dockerfile).
_REQUEST_TIMEOUT_SECONDS = 10
_MAX_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = 0.5

# Resend status codes where retrying is pointless - bad/revoked API key,
# malformed payload, unverified sender domain, etc. Only network-level
# failures, 429 (rate limited), and 5xx are worth a retry.
_NON_RETRYABLE_STATUS_CODES = frozenset({400, 401, 403, 404, 422})


class ResendEmailBackend(BaseEmailBackend):
    """Drop-in EMAIL_BACKEND: every django.core.mail send (this app's own
    OTP emails, and allauth's signup/reset emails) is delivered through
    Resend's API. See module docstring for why this never raises."""

    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        api_key = getattr(settings, "RESEND_API_KEY", "")
        if not api_key:
            logger.warning(
                "RESEND_API_KEY is not set - %d email(s) were NOT sent. "
                "Set RESEND_API_KEY in the environment to actually deliver mail.",
                len(email_messages),
            )
            return 0

        sent_count = 0
        for message in email_messages:
            if self._send_one(message, api_key):
                sent_count += 1
        return sent_count

    def _send_one(self, message, api_key) -> bool:
        payload = _build_payload(message)
        recipients = payload.get("to", [])
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        start = time.monotonic()

        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                response = requests.post(
                    RESEND_API_URL, json=payload, headers=headers, timeout=_REQUEST_TIMEOUT_SECONDS,
                )
            except requests.exceptions.RequestException as exc:
                logger.warning(
                    "Resend send attempt %d/%d raised a network error (%s) to=%s",
                    attempt, _MAX_ATTEMPTS, type(exc).__name__, recipients,
                )
                if attempt < _MAX_ATTEMPTS:
                    time.sleep(_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))
                    continue
                logger.error(
                    "Resend send failed after %d attempts (network error) to=%s", _MAX_ATTEMPTS, recipients,
                )
                return False

            if 200 <= response.status_code < 300:
                logger.info(
                    "Resend email sent to=%s subject=%r status=%d latency=%.3fs attempt=%d/%d",
                    recipients, message.subject, response.status_code,
                    time.monotonic() - start, attempt, _MAX_ATTEMPTS,
                )
                return True

            if response.status_code in _NON_RETRYABLE_STATUS_CODES or attempt == _MAX_ATTEMPTS:
                logger.error(
                    "Resend send failed to=%s status=%d attempt=%d/%d response=%s",
                    recipients, response.status_code, attempt, _MAX_ATTEMPTS, _safe_excerpt(response.text),
                )
                return False

            logger.warning(
                "Resend send attempt %d/%d got retryable status=%d to=%s - retrying",
                attempt, _MAX_ATTEMPTS, response.status_code, recipients,
            )
            time.sleep(_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))

        return False


def _build_payload(message) -> dict:
    """Maps a django.core.mail EmailMessage/EmailMultiAlternatives onto
    Resend's send-email payload shape."""
    html_body = None
    for content, mimetype in getattr(message, "alternatives", None) or []:
        if mimetype == "text/html":
            html_body = content
            break

    payload = {
        "from": message.from_email or getattr(settings, "DEFAULT_FROM_EMAIL", ""),
        "to": list(message.to),
        "subject": message.subject,
    }
    if message.body:
        payload["text"] = message.body
    if html_body:
        payload["html"] = html_body
    if "text" not in payload and "html" not in payload:
        payload["text"] = ""  # Resend requires at least one of html/text present
    if message.cc:
        payload["cc"] = list(message.cc)
    if message.bcc:
        payload["bcc"] = list(message.bcc)
    if message.reply_to:
        payload["reply_to"] = list(message.reply_to)
    return payload


def _safe_excerpt(response_text: str, limit: int = 200) -> str:
    """Truncates Resend's own error response for logging - never the API
    key (never present in a response body), just a length cap so a
    pathological response can't bloat the log."""
    if not response_text:
        return ""
    return response_text[:limit]
