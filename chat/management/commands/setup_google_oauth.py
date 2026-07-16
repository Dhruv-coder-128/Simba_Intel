"""Re-runnable counterpart to chat/migrations/0025_setup_google_socialapp.py -
that migration bootstraps the Google SocialApp row once; this command lets
you re-sync it any time (e.g. after rotating GOOGLE_CLIENT_ID/
GOOGLE_CLIENT_SECRET in the environment) without writing a new migration
for what is really just "read two env vars into one row".

Usage:
    python manage.py setup_google_oauth
"""
from django.conf import settings
from django.contrib.sites.models import Site
from django.core.management.base import BaseCommand

from allauth.socialaccount.models import SocialApp


class Command(BaseCommand):
    help = "Creates/updates the Google SocialApp row from GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET."

    def handle(self, *args, **options):
        import os
        client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
        client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")

        if not client_id or not client_secret:
            self.stdout.write(self.style.ERROR(
                "GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET are not set in this environment - nothing to do."
            ))
            return

        site = Site.objects.get(id=settings.SITE_ID)
        app, created = SocialApp.objects.get_or_create(
            provider="google", defaults={"name": "Google", "client_id": client_id, "secret": client_secret},
        )
        if not created:
            app.client_id = client_id
            app.secret = client_secret
            app.save(update_fields=["client_id", "secret"])
        app.sites.add(site)

        self.stdout.write(self.style.SUCCESS(
            f"Google SocialApp {'created' if created else 'updated'} and linked to site '{site.domain}'."
        ))
