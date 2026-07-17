"""Background processing (Part 8) - routine housekeeping that has no
business running inline in a request. Deliberately conservative about what
it touches: UsageEvent (the analytics/billing history) and unresolved
ErrorLog rows are never deleted here, since that data has ongoing value and
this project has no separate rollup table to fall back on for historical
figures once raw rows are gone. Intended for a daily Render Cron Job.

Three independent, individually-reported cleanup jobs:
  1. Expired Django sessions (django.contrib.sessions) - the same as
     Django's own `clearsessions` management command; reimplemented as one
     step here so a single cron entry covers all of this project's routine
     cleanup instead of needing several separately scheduled commands.
  2. UserSession rows (this project's own "active sessions" list shown in
     Settings > Security) whose underlying Django session already expired
     or was logged out elsewhere - these otherwise linger forever, since
     nothing else ever prunes them.
  3. ErrorLog rows already marked resolved, past a retention window -
     unresolved errors are never touched regardless of age.
"""
from datetime import timedelta

from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand
from django.utils import timezone

from chat.models import ErrorLog, UserSession


class Command(BaseCommand):
    help = "Routine housekeeping: expired sessions, orphaned UserSession rows, and old resolved ErrorLog entries."

    def add_arguments(self, parser):
        parser.add_argument(
            "--resolved-error-retention-days", type=int, default=90,
            help="Delete resolved ErrorLog rows older than this many days (default 90). Unresolved rows are never deleted.",
        )

    def handle(self, *args, **options):
        now = timezone.now()

        expired_sessions_count, _ = Session.objects.filter(expire_date__lt=now).delete()
        self.stdout.write(f"Expired Django sessions removed: {expired_sessions_count}")

        live_session_keys = set(Session.objects.values_list("session_key", flat=True))
        orphaned_qs = UserSession.objects.exclude(session_key__in=live_session_keys)
        orphaned_count = orphaned_qs.count()
        orphaned_qs.delete()
        self.stdout.write(f"Orphaned UserSession rows removed: {orphaned_count}")

        retention_days = options["resolved_error_retention_days"]
        cutoff = now - timedelta(days=retention_days)
        old_resolved_qs = ErrorLog.objects.filter(resolved=True, resolved_at__lt=cutoff)
        old_resolved_count = old_resolved_qs.count()
        old_resolved_qs.delete()
        self.stdout.write(f"Resolved ErrorLog rows older than {retention_days}d removed: {old_resolved_count}")

        self.stdout.write(self.style.SUCCESS("Cleanup complete."))
