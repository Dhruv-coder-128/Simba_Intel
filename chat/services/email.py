"""Centralized outbound email for this app - password-reset OTP codes today,
and the one place any future transactional email (welcome emails, security
notifications, etc.) should be added, via send_html_email().

Actual delivery lives in chat/services/resend_backend.py, a custom Django
EMAIL_BACKEND that sends through the Resend HTTP API. Everything here is a
thin business-logic layer on top of Django's own send_mail()/
EmailMultiAlternatives, which is what routes into that backend - and, for
django-allauth's own signup-confirmation and password-reset-by-link emails,
already does so with zero changes needed in this module or in
chat/adapters.py.

History: this app used to speak SMTP directly to Gmail. Render's outbound
network cannot reach smtp.gmail.com at all (OSError: [Errno 101] Network is
unreachable - a routing/firewall restriction, not a timeout or credentials
problem), so no amount of SMTP hardening could fix it; SMTP has been
removed entirely. Resend's HTTPS API travels over the same outbound path
this app already uses for Groq/Mistral/Tavily, which does work from Render.
"""
import logging
import os

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, send_mail

logger = logging.getLogger(__name__)


def log_email_configuration():
    """Logs the resolved email configuration once at process startup
    (chat/apps.py's ChatConfig.ready()) - confirms Render's environment
    variables actually made it into Django's settings, without ever logging
    the API key itself. Also the single place that warns about the two
    most common silent misconfigurations: the console backend still being
    active, or RESEND_API_KEY being unset while the Resend backend is."""
    backend = getattr(settings, "EMAIL_BACKEND", "")
    api_key_set = bool(getattr(settings, "RESEND_API_KEY", ""))
    logger.info(
        "Email config: backend=%s resend_api_key_set=%s from=%s debug=%s database_url_set=%s",
        backend, api_key_set, getattr(settings, "DEFAULT_FROM_EMAIL", None), settings.DEBUG,
        bool(os.environ.get("DATABASE_URL")),
    )
    if backend == "django.core.mail.backends.console.EmailBackend":
        logger.warning(
            "EMAIL_BACKEND is the console backend - no email is actually being "
            "sent over the network; OTP/verification codes only print to this "
            "process's stdout. Set EMAIL_BACKEND=chat.services.resend_backend."
            "ResendEmailBackend (the default) with a real RESEND_API_KEY to "
            "send real email."
        )
    elif backend == "chat.services.resend_backend.ResendEmailBackend" and not api_key_set:
        logger.warning(
            "EMAIL_BACKEND is ResendEmailBackend but RESEND_API_KEY is not set - "
            "every email send will be logged and skipped until it's configured."
        )


class EmailSendResult:
    def __init__(self, success: bool, error: str = ""):
        self.success = success
        self.error = error


def send_otp_email(user, otp) -> EmailSendResult:
    """Sends the password-reset OTP code. Never raises - degrades to a
    logged, user-facing-safe EmailSendResult instead, so a Resend outage can
    never turn into a 500 or crash the forgot-password/resend-OTP/admin-
    reset-password flows."""
    subject = "Your Simba Intel password reset code"
    message = (
        f"Your password reset code is {otp.code}.\n\n"
        f"It expires in {otp.OTP_VALID_MINUTES} minutes. "
        "If you didn't request this, you can safely ignore this email."
    )
    return _send(subject, message, [user.email])


def send_html_email(to_email, subject, text_body, html_body=None, reply_to=None) -> EmailSendResult:
    """Generic reusable primitive for any future transactional email
    (welcome emails, security notifications, etc.) - adding a new email
    type is one call to this function, never a new API integration."""
    return _send(subject, text_body, [to_email], html_body=html_body, reply_to=reply_to)


def _send(subject, text_body, recipients, html_body=None, reply_to=None) -> EmailSendResult:
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None) or "onboarding@resend.dev"
    try:
        if html_body:
            msg = EmailMultiAlternatives(subject, text_body, from_email, recipients, reply_to=reply_to)
            msg.attach_alternative(html_body, "text/html")
            sent = msg.send(fail_silently=False)
        else:
            sent = send_mail(subject, text_body, from_email, recipients, fail_silently=False)
    except Exception:
        logger.exception("Unexpected error while sending email to=%s subject=%r", recipients, subject)
        return EmailSendResult(False, "Something went wrong sending the email. Please try again shortly.")

    if sent:
        return EmailSendResult(True)
    logger.error(
        "Email to=%s subject=%r was not delivered (see ResendEmailBackend logs above for the reason)",
        recipients, subject,
    )
    return EmailSendResult(False, "Could not send email right now. Please try again shortly.")
