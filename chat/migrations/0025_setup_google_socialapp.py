"""Root cause of Google Login being completely broken: no SocialApp row for
the 'google' provider has ever existed in the database (confirmed by direct
query: SocialApp.objects.all() returns nothing), even though
GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET have been sitting unused in .env this
whole time. django-allauth cannot even build the "Continue with Google"
authorization URL without that row - there is no code bug to fix here, the
Google login button has simply never had credentials to construct a
request with.

This bootstraps that row automatically from GOOGLE_CLIENT_ID/
GOOGLE_CLIENT_SECRET (env vars) on every deploy - both locally and on
Render (see render.yaml, which now declares those two as secrets) - so this
can never again be a manual "remember to click around in Django admin"
step. Safe to run with the env vars unset (logs a clear warning and no-ops,
same fail-gracefully pattern as chat/services/resend_backend.py) - it never
overwrites a SocialApp that was already configured with different values by
hand, only creates/updates from whatever the env vars currently say.

See chat/management/commands/setup_google_oauth.py for the same logic,
re-runnable any time to pick up rotated credentials without a new migration.
"""
import os

from django.db import migrations


def setup_google_socialapp(apps, schema_editor):
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        print(
            "\n[0025_setup_google_socialapp] GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET "
            "not set in this environment - skipping. Google Login will not work "
            "until both are set and this is re-run (see "
            "`python manage.py setup_google_oauth`)."
        )
        return

    Site = apps.get_model("sites", "Site")
    SocialApp = apps.get_model("socialaccount", "SocialApp")

    from django.conf import settings
    site, _ = Site.objects.get_or_create(
        id=settings.SITE_ID, defaults={"domain": "example.com", "name": "example.com"},
    )

    app, created = SocialApp.objects.get_or_create(
        provider="google", defaults={"name": "Google", "client_id": client_id, "secret": client_secret},
    )
    if not created:
        app.client_id = client_id
        app.secret = client_secret
        app.save(update_fields=["client_id", "secret"])
    app.sites.add(site)
    print(f"\n[0025_setup_google_socialapp] Google SocialApp {'created' if created else 'updated'} and linked to site '{site.domain}'.")


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0024_alter_adminauditlog_action"),
        ("sites", "0001_initial"),
        ("socialaccount", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(setup_google_socialapp, noop_reverse),
    ]
