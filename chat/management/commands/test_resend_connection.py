"""Standalone Resend connectivity check - proves, rather than assumes,
that RESEND_API_KEY and EMAIL_BACKEND are actually wired up correctly in
whatever environment this runs in. Replaces the old test_smtp_connection
command from the Gmail-SMTP era (SMTP has been removed entirely - Render
cannot reach smtp.gmail.com at all).

Usage:
    python manage.py test_resend_connection
        Read-only auth check: calls Resend's /domains endpoint, which
        requires a valid API key but sends nothing - safe to run anytime.

    python manage.py test_resend_connection --to someone@example.com
        Sends one real test email through the exact same code path
        (chat.services.email.send_html_email) this app uses for everything
        else, so a pass/fail here is a pass/fail for the real app.
"""
import requests
from django.conf import settings
from django.core.management.base import BaseCommand

RESEND_DOMAINS_URL = "https://api.resend.com/domains"


class Command(BaseCommand):
    help = "Standalone Resend API connectivity check using this project's actual email settings."

    def add_arguments(self, parser):
        parser.add_argument(
            "--to", default=None,
            help="If given, actually sends a test email to this address via the real send path.",
        )

    def handle(self, *args, **options):
        backend = settings.EMAIL_BACKEND
        api_key = getattr(settings, "RESEND_API_KEY", "")
        to_addr = options.get("to")

        self.stdout.write(self.style.MIGRATE_HEADING("Resend connectivity check"))
        self.stdout.write(f"backend={backend} from={settings.DEFAULT_FROM_EMAIL} api_key_set={bool(api_key)}\n")

        if backend != "chat.services.resend_backend.ResendEmailBackend":
            self.stdout.write(self.style.WARNING(
                f"EMAIL_BACKEND is '{backend}', not ResendEmailBackend - there is nothing "
                "for this check to test. Set EMAIL_BACKEND=chat.services.resend_backend."
                "ResendEmailBackend to test the actual production path."
            ))
            return

        if not api_key:
            self.stdout.write(self.style.ERROR(
                "RESEND_API_KEY is not set - every email send will be logged and skipped. "
                "Set it in the environment and re-run this check."
            ))
            return

        if to_addr:
            from chat.services.email import send_html_email
            result = send_html_email(
                to_addr, "SIMBA_INTEL Resend connectivity test",
                "This is a standalone Resend connectivity test - see "
                "chat/management/commands/test_resend_connection.py.",
            )
            if result.success:
                self.stdout.write(self.style.SUCCESS(f"Test email sent to {to_addr}."))
            else:
                self.stdout.write(self.style.ERROR(f"Send failed: {result.error} (see logs above for the exact cause)"))
            return

        try:
            response = requests.get(
                RESEND_DOMAINS_URL, headers={"Authorization": f"Bearer {api_key}"}, timeout=10,
            )
        except requests.exceptions.RequestException as exc:
            self.stdout.write(self.style.ERROR(
                f"Network error reaching Resend's API ({type(exc).__name__}) - this points at an "
                "outbound network restriction in this environment, not at the API key itself."
            ))
            return

        if response.status_code == 200:
            self.stdout.write(self.style.SUCCESS(
                "API key accepted - Resend is reachable and authenticated from here. "
                "Pass --to you@example.com to send a real test email."
            ))
        elif response.status_code in (401, 403):
            self.stdout.write(self.style.ERROR(
                f"Resend rejected the API key (status={response.status_code}) - RESEND_API_KEY "
                "is set but invalid or revoked."
            ))
        else:
            self.stdout.write(self.style.ERROR(f"Unexpected response from Resend: status={response.status_code}"))
