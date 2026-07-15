"""Prints a row count per model, across every installed app - not just
`chat`. Built for one specific job: run it against SQLite before the
Postgres data migration, run it again against Postgres after loaddata, and
diff the two outputs by eye. A row-count mismatch is the cheapest possible
signal that something didn't transfer - it won't catch subtler corruption,
but it catches the two failure modes that actually happen in practice
(a fixture load that silently skips a model due to a natural-key/FK issue,
or an export that ran against the wrong database).
"""
from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Print row counts for every model in every installed app, plus which database engine answered."

    def handle(self, *args, **options):
        engine = connection.settings_dict['ENGINE'].rsplit('.', 1)[-1]
        db_name = connection.settings_dict['NAME']
        self.stdout.write(self.style.MIGRATE_HEADING(f"Database: {engine} / {db_name}"))
        self.stdout.write("")

        total = 0
        rows = []
        for model in sorted(apps.get_models(), key=lambda m: (m._meta.app_label, m._meta.model_name)):
            label = f"{model._meta.app_label}.{model._meta.object_name}"
            try:
                count = model.objects.count()
            except Exception as e:
                rows.append((label, f"ERROR: {e}"))
                continue
            rows.append((label, count))
            if isinstance(count, int):
                total += count

        width = max(len(label) for label, _ in rows) + 2
        for label, count in rows:
            self.stdout.write(f"{label.ljust(width)} {count}")

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Total rows across all models: {total}"))
